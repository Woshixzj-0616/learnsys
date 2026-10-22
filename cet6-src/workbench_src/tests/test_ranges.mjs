// 纯函数测试：整段/整篇区间 + 直接问的上下文载荷。
// 运行：node --test D:\cet6_tool\workbench_src\tests\test_ranges.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const code = fs.readFileSync(path.join(here, "..", "js", "25-ranges.js"), "utf8");
const sandbox = {window: {}};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const WB = sandbox.window.WB;

test("itemRange 包含正文和题目", () => {
  const range = WB.ranges.itemRange({
    content: {start: 42.38, end: 170.72},
    questions: {start: 171.42, end: 233.26},
  });
  assert.equal(range.start, 42.18);
  assert.equal(range.end, 233.76);
});

test("itemRange 没有题目时到正文结束", () => {
  const range = WB.ranges.itemRange({
    content: {start: 10, end: 30},
    questions: {start: 0, end: 0},
  });
  assert.equal(range.start, 9.8);
  assert.equal(range.end, 30.5);
});

test("itemRange 时间异常也不会产生负区间", () => {
  const range = WB.ranges.itemRange({
    content: {start: 100, end: 50},
    questions: {},
  });
  assert.ok(range.end > range.start);
  assert.ok(range.start >= 0);
});

test("itemRange 空对象安全", () => {
  const range = WB.ranges.itemRange(null);
  assert.equal(range.start, 0);
  assert.equal(range.end, 0);
});

test("sectionRange 正常与缺字段", () => {
  const normal = WB.ranges.sectionRange({start: 7.08, end: 438.18});
  assert.equal(normal.start, 7.08);
  assert.equal(normal.end, 438.18);
  const fallback = WB.ranges.sectionRange({start: 5});
  assert.equal(fallback.start, 5);
  assert.ok(fallback.end > fallback.start);
  const empty = WB.ranges.sectionRange(null);
  assert.equal(empty.start, 0);
  assert.equal(empty.end, 0);
});

test("contextPayload 带齐学习现场", () => {
  const payload = WB.contextPayload({
    itemId: "A-1",
    title: "测试卷 / Section A / Conversation 1",
    sentence: 3,
    en: "make out",
    selection: "make out",
    errors: {3: ["连读"]},
    notes: {3: "语速太快"},
    loopStats: {3: {loops: 4, plays: 6}},
    recentActions: [{text: "播放第 3 句"}],
  });
  assert.equal(payload.surface, "cet6");
  assert.equal(payload.object_id, "A-1");
  assert.equal(payload.selection, "make out");
  assert.equal(payload.surrounding.en, "make out");
  assert.equal(payload.learning_state.sentence, 3);
  assert.deepEqual([...payload.learning_state.tags], ["连读"]);
  assert.equal(payload.learning_state.loops, 4);
  assert.equal(payload.learning_state.plays, 6);
  assert.equal(payload.provenance.source, "cet6");
  assert.equal(payload.recent_actions.length, 1);
});

test("contextPayload 未选中句子时句子号为 -1", () => {
  const payload = WB.contextPayload({itemId: "A-1", sentence: -1});
  assert.equal(payload.learning_state.sentence, -1);
  assert.equal(payload.learning_state.tags.length, 0);
  assert.equal(Object.keys(payload.surrounding).length, 0);
});

test("contextPayload 截断超长选区", () => {
  const payload = WB.contextPayload({itemId: "A-1", selection: "x".repeat(5000)});
  assert.equal(payload.selection.length, 2000);
});

test("contextPayload 带前后句、本段原文和进度", () => {
  const payload = WB.contextPayload({
    itemId: "A-1", sentence: 2, en: "current",
    before: "before", after: "after",
    section: "Section A", item: "Conversation 1",
    itemText: "a b current after", questionText: "Q1?",
    done: true, paperDone: 12, paperTotal: 40,
  });
  assert.equal(payload.surrounding["前一句"], "before");
  assert.equal(payload.surrounding["后一句"], "after");
  assert.equal(payload.surrounding["本段原文"], "a b current after");
  assert.equal(payload.surrounding["题目文本"], "Q1?");
  assert.equal(payload.learning_state.section, "Section A");
  assert.equal(payload.learning_state.done, true);
  assert.equal(payload.learning_state.paper_done, 12);
  assert.equal(payload.learning_state.paper_total, 40);
});

test("sentenceTimeline 使用手动起点并压平整卷", () => {
  const paper = {
    sections: [{
      letter: "A", name: "Section A",
      items: [
        {index: 1, title: "Conversation 1", sentences: [
          {i: 1, start: 10, end: 12, en: "one"},
          {i: 2, start: 13, end: 16, en: "two"},
        ]},
        {index: 2, title: "Conversation 2", sentences: [
          {i: 3, start: 20, end: 23, en: "three"},
        ]},
      ],
    }],
  };
  const timeline = WB.ranges.sentenceTimeline(paper, {"A-1": {"2": 14.5}});
  assert.equal(timeline.length, 3);
  assert.equal(timeline[0].start, 10);
  assert.equal(timeline[1].start, 14.5);
  assert.equal(timeline[1].end, 16.28);
  assert.equal(timeline[2].i, 3);
  assert.equal(WB.ranges.sentenceAt(timeline, 15).i, 2);
  assert.equal(WB.ranges.sentenceAt(timeline, 21).i, 3);
  assert.equal(WB.ranges.sentenceAt(timeline, 50), null);
});

test("sentenceAt 容忍句间空隙，不来回闪", () => {
  const timeline = WB.ranges.sentenceTimeline({
    sections: [{letter: "A", items: [{index: 1, title: "x", sentences: [
      {i: 1, start: 10, end: 12},
      {i: 2, start: 13, end: 15},
    ]}]}],
  }, {});
  assert.equal(WB.ranges.sentenceAt(timeline, 12.2).i, 1);
  assert.equal(WB.ranges.sentenceAt(timeline, 13.1).i, 2);
});
