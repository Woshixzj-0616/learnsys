// 做题面板纯逻辑：判分、选择、重做。
// 运行：node --test D:\cet6_tool\workbench_src\tests\test_quiz.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "..", "js", "67-quiz.js"), "utf8");

function setup(questions) {
  const sandbox = { console };
  sandbox.window = sandbox;
  sandbox.WB = {
    util: {},
    state: {},
    session: { paperDir: "p1" },
    store: { saveState() {} },
    render: { questions() {} },
    status() {},
    api: { ready: false },
    cet6Sync: {},
    paper: {
      currentItemId: () => "A-1",
      currentSection: () => ({ name: "Section A" }),
      currentItem: () => ({ title: "Conversation 1" }),
      quizForItem: () => ({ questions }),
    },
  };
  vm.runInNewContext(source, sandbox);
  return sandbox.WB;
}

test("grade 按题号判错，未答也算错", () => {
  const WB = setup({ 1: { answer: "B" }, 2: { answer: "C" } });
  const one = WB.quiz.grade({ 1: { answer: "B" }, 2: { answer: "C" } }, { 1: "B" });
  assert.equal(JSON.stringify(one), JSON.stringify({ wrong: [2], correct: 1, total: 2 }));
  const none = WB.quiz.grade({ 1: { answer: "B" } }, {});
  assert.equal(JSON.stringify(none), JSON.stringify({ wrong: [1], correct: 0, total: 1 }));
});

test("选择写进状态，重做清空本题组", () => {
  const WB = setup({ 1: { answer: "B" } });
  WB.quiz.choose("1", "b");
  assert.equal(WB.state.quiz["A-1"].answers["1"], "B");
  WB.quiz.redo();
  assert.equal(WB.state.quiz["A-1"], undefined);
});
