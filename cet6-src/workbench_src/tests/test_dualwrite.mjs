// 纯函数测试：服务端行映射、整卷快照、空快照判断、结构指纹。
// 运行：node --test D:\cet6_tool\workbench_src\tests\test_dualwrite.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const js = path.join(here, "..", "js");
const sandbox = {
  window: {},
  location: {protocol: "http:"},
  document: {addEventListener(){}, readyState: "complete", getElementById(){ return null; }},
  console,
};
vm.createContext(sandbox);
for (const name of ["00-core.js", "04-mode.js", "56-dualwrite.js"]) {
  vm.runInContext(fs.readFileSync(path.join(js, name), "utf8"), sandbox);
}
const WB = sandbox.window.WB;
const D = WB.dualwrite;

function paper() {
  return {
    title: "测试卷",
    sections: [{
      letter: "A",
      name: "Section A 短对话",
      items: [
        {index: 1, title: "Conversation 1", sentences: [{i: 1, en: "a"}, {i: 2, en: "b"}]},
        {index: 2, title: "Conversation 2", sentences: [{i: 1, en: "c"}]},
      ],
    }, {
      letter: "B",
      name: "Section B 长对话",
      items: [{index: 1, title: "Conversation 1", sentences: [{i: 1, en: "d"}]}],
    }],
  };
}

function emptyState() {
  return {done: {}, errors: {}, notes: {}, loopStats: {}, starts: {}, ab: {}, pos: null};
}

test("sectionLetter 能取 Section A / 小写 / 中文后缀", () => {
  assert.equal(D.sectionLetter("Section A 短对话"), "A");
  assert.equal(D.sectionLetter("section b"), "B");
  assert.equal(D.sectionLetter("没有字母"), "");
});

test("Section 精确匹配优先，字母回退只在唯一时生效", () => {
  const sections = paper().sections;
  assert.equal(D.pickSection(sections, "Section A 短对话").letter, "A");
  assert.equal(D.pickSection(sections, "Section A").letter, "A");
  assert.equal(D.pickSection(sections, "Section Z"), null);
});

test("item 精确匹配、尾号回退、歧义不猜", () => {
  const sec = paper().sections[0];
  assert.equal(D.pickItem(sec, "Conversation 1").index, 1);
  assert.equal(D.pickItem(sec, "Conversation 2").index, 2);
  assert.equal(D.pickItem(sec, "Conversation"), null);
  const dup = {letter: "A", items: [
    {index: 1, title: "Conversation 1"}, {index: 1, title: "Conversation 1"},
  ]};
  assert.equal(D.pickItem(dup, "Conversation 1"), null);
});

test("服务端行映射到本地 state", () => {
  const mapped = D.mapServerState(paper(), [{
    section: "Section A 短对话", item: "Conversation 1",
    sentences: [{sentence: 1, done: true, tags: ["连读"], note: "太快", loops: 2, plays: 3}],
  }]);
  assert.equal(mapped.matched, 1);
  assert.equal(mapped.meaningful, 1);
  assert.equal(mapped.state.done["A-1"][1], true);
  assert.equal(mapped.state.errors["A-1"][1].join(","), "连读");
  assert.equal(mapped.state.notes["A-1"][1], "太快");
  assert.equal(mapped.state.loopStats["A-1"][1].loops, 2);
  assert.equal(mapped.state.loopStats["A-1"][1].plays, 3);
});

test("结构对不上的段进 skipped，不猜也不写", () => {
  const mapped = D.mapServerState(paper(), [
    {section: "Section Z", item: "Conversation 9", sentences: [{sentence: 1}]},
    {section: "Section A 短对话", item: "Conversation 1", sentences: [{sentence: 99}]},
  ]);
  assert.equal(mapped.unmatched, 1);
  assert.equal(mapped.partial, 1);
  assert.equal(mapped.skipped.length, 2);
  assert.equal(Object.keys(mapped.state.done).length, 0);
});

test("mergeIntoState：本地优先只补缺口，服务端优先覆盖非空笔记", () => {
  const mapped = D.mapServerState(paper(), [{
    section: "Section A 短对话", item: "Conversation 1",
    sentences: [{sentence: 1, note: "服务端", tags: ["连读"]}],
  }]);
  const local = emptyState();
  local.notes["A-1"] = {1: "本地"};
  D.mergeIntoState(local, mapped, false);
  assert.equal(local.notes["A-1"][1], "本地");
  D.mergeIntoState(local, mapped, true);
  assert.equal(local.notes["A-1"][1], "服务端");
  assert.equal(local.errors["A-1"][1].join(","), "连读");
});

test("canonicalRows 生成整卷快照与 done 列表", () => {
  const state = emptyState();
  state.done["A-1"] = {1: true, 2: true};
  state.errors["A-1"] = {1: ["连读"]};
  state.notes["A-1"] = {2: "从句"};
  state.loopStats["A-1"] = {1: {loops: 2, plays: 3}};
  const built = D.canonicalRows(paper(), state, []);
  assert.equal(built.items.length, 3);
  const first = built.items[0];
  assert.equal(first.section, "Section A 短对话");
  assert.equal(first.done.join(","), "1,2");
  assert.equal(first.sentences[0].tags[0], "连读");
  assert.equal(first.sentences[1].note, "从句");
  assert.equal(first.sentences[0].loops, 2);
});

test("canonicalRows 跳过结构不一致的段", () => {
  const built = D.canonicalRows(paper(), emptyState(),
    [{section: "Section A 短对话", item: "Conversation 1"}]);
  assert.equal(built.items.length, 2);
  assert.ok(built.items.every(it => it.item !== "Conversation 1" || it.section !== "Section A 短对话"));
});

test("snapshotIsEmpty 只看 4 个同步字段", () => {
  const state = emptyState();
  state.starts = {"A-1": {1: 12}};
  state.ab = {"A-1": {1: {a: 1, b: 2}}};
  state.pos = {si: 0, ii: 1};
  state.translation = {"A-1": {1: {translation: "x"}}};
  assert.equal(D.snapshotIsEmpty(state), true);
  state.done["A-1"] = {1: true};
  assert.equal(D.snapshotIsEmpty(state), false);
});

test("paperSig 对结构变化敏感", () => {
  const a = D.paperSig(paper());
  const changed = paper();
  changed.sections[0].items[0].sentences.push({i: 3, en: "new"});
  assert.notEqual(a, D.paperSig(changed));
});

test("clientDay 是本地日期 YYYY-MM-DD", () => {
  assert.match(D.clientDay(), /^\d{4}-\d{2}-\d{2}$/);
});
