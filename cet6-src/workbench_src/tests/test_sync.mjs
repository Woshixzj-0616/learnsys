// 同步层测试：防抖期间切段落，改过的每一条都要推上去，不能只推当前条。
// 运行：node --test D:\cet6_tool\workbench_src\tests\test_sync.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const js = path.join(here, "..", "js");
const sandbox = {
  window: { addEventListener() {} },
  location: { protocol: "http:" },
  document: {
    addEventListener() {},
    readyState: "complete",
    visibilityState: "visible",
    getElementById() { return null; },
    createElement() { return { classList: { add() {}, remove() {} }, setAttribute() {} }; },
    querySelector() { return null; },
    body: {},
  },
  console,
  setTimeout,
  clearTimeout,
};
vm.createContext(sandbox);
for (const name of ["00-core.js", "04-mode.js", "56-dualwrite.js", "58-sync.js"]) {
  vm.runInContext(fs.readFileSync(path.join(js, name), "utf8"), sandbox);
}
const WB = sandbox.window.WB;

function makePaper() {
  return {
    title: "测试卷",
    sections: [{
      name: "Section A 短对话",
      items: [
        { title: "Conversation 1", sentences: [{ i: 1, en: "a" }] },
        { title: "Conversation 2", sentences: [{ i: 1, en: "b" }] },
      ],
    }],
  };
}

function setup() {
  const paper = makePaper();
  WB.session = { paper, paperDir: "测试卷" };
  WB.state = { done: {}, errors: {}, notes: {}, loopStats: {}, starts: {}, ab: {}, pos: null };
  let si = 0;
  WB.paper = {
    currentSection() { return paper.sections[0]; },
    currentItem() { return paper.sections[0].items[si]; },
    itemId(sec, cur) { return sec.name + "|" + cur.title; },
  };
  const calls = [];
  WB.api = {
    ready: true,
    async post(url, payload) { calls.push({ url, payload }); return true; },
    async get() { return { items: [] }; },
  };
  return { calls, switchTo(n) { si = n; } };
}

test("防抖期间切换条目：两条都推送，不只推当前条", async () => {
  const { calls, switchTo } = setup();
  WB.cet6Sync.schedule();
  switchTo(1);
  WB.cet6Sync.schedule();
  await WB.cet6Sync.flush();
  assert.equal(calls.length, 2);
  assert.deepEqual(calls.map((c) => c.payload.item), ["Conversation 1", "Conversation 2"]);
  assert.ok(calls.every((c) => c.url === "/api/cet6/sync"));
});

test("同一条目重复调度只推一次", async () => {
  const { calls } = setup();
  WB.cet6Sync.schedule();
  WB.cet6Sync.schedule();
  WB.cet6Sync.schedule();
  await WB.cet6Sync.flush();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].payload.item, "Conversation 1");
});

test("没有待推送时不发请求（pagehide 安全）", async () => {
  const { calls } = setup();
  await WB.cet6Sync.flush();
  assert.equal(calls.length, 0);
});
