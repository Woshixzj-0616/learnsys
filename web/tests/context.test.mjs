import assert from "node:assert/strict";
import { test } from "node:test";

import { buildSnapshot, describeSnapshot, MAX_SELECTION } from "../js/context.js";

test("未知键被丢弃，九个键都在", () => {
  const snapshot = buildSnapshot({
    surface: "ask",
    object_type: "material",
    object_id: "12",
    title: "第三章",
    secret: "不该出现",
  });
  assert.equal(snapshot.surface, "ask");
  assert.equal(snapshot.title, "第三章");
  assert.equal("secret" in snapshot, false);
  assert.deepEqual(
    Object.keys(snapshot).sort(),
    ["learning_state", "object_id", "object_type", "provenance",
      "recent_actions", "selection", "surface", "surrounding", "title"],
  );
});

test("选区截断到 2000 字", () => {
  const snapshot = buildSnapshot({ selection: "字".repeat(MAX_SELECTION + 50) });
  assert.equal(snapshot.selection.length, MAX_SELECTION);
});

test("周围内容按值截断，保留数字", () => {
  const snapshot = buildSnapshot({
    surrounding: { sentence: "a".repeat(2000), loops: 3 },
  });
  assert.equal(snapshot.surrounding.sentence.length, 1000);
  assert.equal(snapshot.surrounding.loops, 3);
});

test("最近操作只留前 20 条", () => {
  const snapshot = buildSnapshot({
    recent_actions: Array.from({ length: 30 }, (_, i) => `动作${i}`),
  });
  assert.equal(snapshot.recent_actions.length, 20);
});

test("超过 20KB 抛错", () => {
  const surrounding = {};
  for (let i = 0; i < 30; i += 1) surrounding[`k${i}`] = "x".repeat(1000);
  assert.throws(
    () => buildSnapshot({ surrounding }),
    /上下文太大/,
  );
});

test("摘要优先用标题", () => {
  assert.equal(
    describeSnapshot({ title: "第三章", object_id: "12" }),
    "第三章",
  );
  assert.match(
    describeSnapshot({ title: "第三章", selection: "市场" }),
    /^第三章 · 市场$/,
  );
});
