import assert from "node:assert/strict";
import { test } from "node:test";

import { reviewKey } from "../js/pages/cet6/review-keys.js";

test("输入框里：Ctrl/Cmd+Enter 显示答案，普通 Enter 不劫持", () => {
  assert.equal(reviewKey("Enter", { typing: true, ctrl: true }), "reveal");
  assert.equal(reviewKey("Enter", { typing: true }), "");
  assert.equal(reviewKey(" ", { typing: true }), "");
  assert.equal(reviewKey("3", { typing: true, revealed: true }), "");
});

test("看答案前：空格或 Enter 显示答案", () => {
  assert.equal(reviewKey(" ", { revealed: false }), "reveal");
  assert.equal(reviewKey("Enter", { revealed: false }), "reveal");
});

test("看答案后：1–4 评档，空格/Enter 不重复触发", () => {
  for (const key of ["1", "2", "3", "4"]) {
    assert.equal(reviewKey(key, { revealed: true }), `rate:${key}`);
  }
  assert.equal(reviewKey("5", { revealed: true }), "");
  assert.equal(reviewKey(" ", { revealed: true }), "");
  assert.equal(reviewKey("Enter", { revealed: true }), "");
});
