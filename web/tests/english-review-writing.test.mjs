import assert from "node:assert/strict";
import { test } from "node:test";

import { writingCardHtml } from "../js/pages/english-review-writing.js";

const CARD = {
  pattern: "PATTERN_SENTINEL ... that ...",
  example: "EXAMPLE_SENTINEL makes practice possible.",
  example_zh: "中文例句句",
  question: "中文用途",
  topic: "换题主题",
  note: "NOTE_SENTINEL",
};

function render(view, card = CARD) {
  return writingCardHtml(card, view, {
    metaHtml: "META_SENTINEL",
    ratingsHtml: "RATINGS_SENTINEL",
  });
}

test("第 1 关未展开：只给中文例句，不出现英文句型/例句/提示", () => {
  const html = render({ stage: 1, typed: "", revealed: false, hintUsed: false });
  assert.ok(html.includes("中文例句句"));
  assert.ok(html.includes("META_SENTINEL"));
  assert.ok(html.includes("先给个提示"));
  assert.ok(!html.includes("PATTERN_SENTINEL"));
  assert.ok(!html.includes("EXAMPLE_SENTINEL"));
  assert.ok(!html.includes("NOTE_SENTINEL"));
  assert.ok(!html.includes("RATINGS_SENTINEL"));
});

test("第 2 关未展开：只给中文用途和空位数", () => {
  const html = render({ stage: 2, typed: "", revealed: false, hintUsed: false });
  assert.ok(html.includes("中文用途"));
  assert.ok(html.includes("2 个空位"));
  assert.ok(!html.includes("PATTERN_SENTINEL"));
  assert.ok(!html.includes("EXAMPLE_SENTINEL"));
  assert.ok(!html.includes("NOTE_SENTINEL"));
});

test("第 3 关未展开：给用途和换主题，不给英文答案", () => {
  const html = render({ stage: 3, typed: "", revealed: false, hintUsed: false });
  assert.ok(html.includes("中文用途"));
  assert.ok(html.includes("换题主题"));
  assert.ok(!html.includes("PATTERN_SENTINEL"));
  assert.ok(!html.includes("EXAMPLE_SENTINEL"));
  assert.ok(!html.includes("NOTE_SENTINEL"));

  const fallback = render({ stage: 3, typed: "", revealed: false, hintUsed: false },
    { ...CARD, topic: "" });
  assert.ok(fallback.includes("换一个和参考例句不同的主题"));
});

test("第 1 关点提示：只出现带空位的骨架", () => {
  const html = render({ stage: 1, typed: "", revealed: false, hintUsed: true });
  assert.ok(html.includes("PATTERN_SENTINEL ____ that ____"));
  assert.ok(!html.includes("EXAMPLE_SENTINEL"));
});

test("展开后：参考句型、例句、提示、自评都出现", () => {
  const html = render({ stage: 1, typed: "my translation", revealed: true, hintUsed: false });
  assert.ok(html.includes("PATTERN_SENTINEL"));
  assert.ok(html.includes("EXAMPLE_SENTINEL"));
  assert.ok(html.includes("NOTE_SENTINEL"));
  assert.ok(html.includes("RATINGS_SENTINEL"));
  assert.ok(html.includes("my translation"));
  assert.ok(html.includes("关键词对照"));
});

test("缺句型时不进三关，显示缺内容提示并保留自评出口", () => {
  const html = render({ stage: 0, typed: "", revealed: false, hintUsed: false },
    { ...CARD, pattern: "" });
  assert.ok(html.includes("缺内容"));
  assert.ok(html.includes("RATINGS_SENTINEL"));
  assert.ok(!html.includes("PATTERN_SENTINEL"));
});
