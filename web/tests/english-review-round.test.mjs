import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ROUND_SIZE, cardKey, chineseGloss, clearRound, loadRound, localDay,
  matchesAnswer, normalizeAnswer, saveRound, shouldDecrementQuota, wordPrompt,
} from "../js/pages/english-review-round.js";

function fakeStorage() {
  const data = new Map();
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => { data.set(key, String(value)); },
    removeItem: (key) => { data.delete(key); },
  };
}

test("本轮进度按 kind + 当天保存，跨天失效", () => {
  const store = fakeStorage();
  saveRound(store, "sentence", "2026-11-10", { done: 3 });
  assert.equal(loadRound(store, "sentence", "2026-11-10").done, 3);
  assert.equal(loadRound(store, "sentence", "2026-11-11"), null);
  assert.equal(loadRound(store, "word", "2026-11-10"), null);
  clearRound(store, "sentence", "2026-11-10");
  assert.equal(loadRound(store, "sentence", "2026-11-10"), null);
});

test("done 被夹在 0..10，当前卡草稿能一起恢复", () => {
  const store = fakeStorage();
  saveRound(store, "word", "2026-11-10",
    { done: 99, current: { key: "vocab:1", typed: "rail", revealed: false } });
  const round = loadRound(store, "word", "2026-11-10");
  assert.equal(round.done, ROUND_SIZE);
  assert.equal(round.current.key, "vocab:1");
  assert.equal(round.current.typed, "rail");
});

test("日期用本地日期，不用 toISOString", () => {
  assert.equal(localDay(new Date(2026, 10, 10, 0, 30)), "2026-11-10");
  assert.equal(localDay(new Date(2026, 0, 2, 23, 59)), "2026-01-02");
});

test("卡片 key 与中文词义提取", () => {
  assert.equal(cardKey({ item_type: "accum", item_id: 42 }), "accum:42");
  assert.equal(chineseGloss("住房｜拼写错误 accommodation"), "住房");
  assert.equal(chineseGloss("高铁"), "高铁");
});

test("单词卡方向：中文提示打英文，没有中文时回退", () => {
  const vocab = wordPrompt({ item_type: "vocab", word: "high-speed rail",
    meaning: "高铁｜交通类", context: "The high-speed rail ..." });
  assert.equal(vocab.direction, "zh2en");
  assert.equal(vocab.prompt, "高铁");
  assert.equal(vocab.answer, "high-speed rail");
  assert.equal(vocab.hint, "The high-speed rail ...");

  const accum = wordPrompt({ item_type: "accum", accum_kind: "translation",
    word: "高铁", meaning: "high-speed rail", context: "交通类" });
  assert.equal(accum.direction, "zh2en");
  assert.equal(accum.prompt, "高铁");
  assert.equal(accum.answer, "high-speed rail");

  const fallback = wordPrompt({ item_type: "vocab", word: "subnet",
    meaning: "a smaller network", context: "" });
  assert.equal(fallback.direction, "en2zh");
  assert.equal(fallback.prompt, "subnet");
  assert.equal(fallback.hint, "");
});

test("答案比较：大小写、标点、连字符与多答案都兼容", () => {
  assert.equal(normalizeAnswer("The Belt-and-Road Initiative (BRI)"),
    "the belt and road initiative");
  assert.equal(matchesAnswer("high-speed rail", "High Speed Rail"), "same");
  assert.equal(matchesAnswer("the dual carbon goals", "dual carbon goals"),
    "close");
  assert.equal(matchesAnswer("高铁；高速铁路", "高速铁路"), "same");
  assert.equal(matchesAnswer("高铁", "飞机"), "different");
  assert.equal(matchesAnswer("高铁", "  "), "");
});

test("只有新卡且属于本 tab 配额才扣新卡数", () => {
  assert.equal(shouldDecrementQuota(
    { item_type: "wrong", state: "new" }, ["wrong"]), true);
  assert.equal(shouldDecrementQuota(
    { item_type: "wrong", state: "review" }, ["wrong"]), false);
  assert.equal(shouldDecrementQuota(
    { item_type: "accum", state: "new" }, ["wrong"]), false);
});
