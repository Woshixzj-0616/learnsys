import assert from "node:assert/strict";
import { test } from "node:test";

import { nextRoute } from "../js/nav_bridge.js";

test("首次收到跳转就应用", () => {
  const next = nextRoute({ server: "", last: 0 },
    { server: "s1", seq: 3, href: "#/quiz" });
  assert.equal(next.href, "#/quiz");
  assert.deepEqual(next.state, { server: "s1", last: 3 });
});

test("同序号不重复应用", () => {
  const next = nextRoute({ server: "s1", last: 3 },
    { server: "s1", seq: 3, href: "#/quiz" });
  assert.equal(next.href, "");
  assert.deepEqual(next.state, { server: "s1", last: 3 });
});

test("更小的序号不应用", () => {
  const next = nextRoute({ server: "s1", last: 5 },
    { server: "s1", seq: 2, href: "#/old" });
  assert.equal(next.href, "");
  assert.equal(next.state.last, 5);
});

test("空 href（过期/没有）不跳", () => {
  const next = nextRoute({ server: "s1", last: 1 },
    { server: "s1", seq: 2, href: "" });
  assert.equal(next.href, "");
  assert.equal(next.state.last, 1);
});

test("后台重启后序号归零再应用", () => {
  const next = nextRoute({ server: "s1", last: 9 },
    { server: "s2", seq: 1, href: "#/materials" });
  assert.equal(next.href, "#/materials");
  assert.deepEqual(next.state, { server: "s2", last: 1 });
});

test("后台重启但没有待跳转：只更新 server", () => {
  const next = nextRoute({ server: "s1", last: 9 },
    { server: "s2", seq: 0, href: "" });
  assert.equal(next.href, "");
  assert.deepEqual(next.state, { server: "s2", last: 0 });
});

test("奇形怪状的 payload 不崩", () => {
  for (const payload of [null, undefined, {}, { server: "s1" }]) {
    const next = nextRoute(null, payload);
    assert.equal(next.href, "");
  }
});
