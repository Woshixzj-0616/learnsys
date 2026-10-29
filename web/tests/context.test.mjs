import assert from "node:assert/strict";
import { test } from "node:test";

import { buildSnapshot, describeSnapshot } from "../js/context.js";

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

// 上限归后端（learnsys/context.py）；前端若再截一份，就会出现两个真相源。
test("前端不截断，长文本原样交给后端", () => {
  const long = "字".repeat(5000);
  const snapshot = buildSnapshot({ selection: long });
  assert.equal(snapshot.selection.length, 5000);
});

test("前端不裁条数，最近操作原样交给后端", () => {
  const actions = Array.from({ length: 30 }, (_, i) => `动作${i}`);
  const snapshot = buildSnapshot({ recent_actions: actions });
  assert.equal(snapshot.recent_actions.length, 30);
});

test("周围内容只归一形状，保留数字", () => {
  const snapshot = buildSnapshot({
    surrounding: { sentence: "a".repeat(2000), loops: 3 },
  });
  assert.equal(snapshot.surrounding.sentence.length, 2000);
  assert.equal(snapshot.surrounding.loops, 3);
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
