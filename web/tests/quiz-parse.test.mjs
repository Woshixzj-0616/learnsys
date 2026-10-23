import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildAttemptPayload,
  parseGrading,
  parseKnowledge,
  parseLastQuestion,
  parseQuestionBlocks,
  parseQuestionStem,
} from "../js/pages/quiz-parse.js";

test("题块解析：题号、知识点、题干去掉知识点行", () => {
  const text = "【第1题】The speaker implies what?\n【知识点】听力推断、词汇\n\n【第2题】What is the main idea?\n【知识点】听力主旨";
  const blocks = parseQuestionBlocks(text);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].no, 1);
  assert.equal(blocks[0].stem, "The speaker implies what?");
  assert.deepEqual(blocks[0].points, ["听力推断", "词汇"]);
  assert.equal(blocks[1].no, 2);
  assert.deepEqual(blocks[1].points, ["听力主旨"]);
});

test("取最后一个题块；题号支持空格", () => {
  const text = "【第 1 题】A\n【知识点】词汇\n【第 2 题】B\n【知识点】语法";
  const last = parseLastQuestion(text);
  assert.equal(last.no, 2);
  assert.equal(last.stem, "B");
  assert.deepEqual(last.points, ["语法"]);
});

test("批改只解析最后一个【批改】，且不把下一题知识点算进来", () => {
  const text = "【批改】正确\n方向对。\n【第2题】下一题\n【知识点】阅读";
  const grading = parseGrading(text);
  assert.equal(grading.found, true);
  assert.equal(grading.correct, true);
  assert.equal(grading.body, "方向对。");
  const last = parseLastQuestion(text);
  assert.deepEqual(last.points, ["阅读"]);
});

test("批改否定词优先：部分正确/不正确/基本正确都算错", () => {
  for (const line of ["部分正确", "不完全正确", "不正确", "基本正确", "错误", "答错了"]) {
    const grading = parseGrading(`【批改】${line}\n原因`);
    assert.equal(grading.correct, false, line);
  }
  assert.equal(parseGrading("【批改】正确").correct, true);
  assert.equal(parseGrading("【批改】**完全正确**").correct, true);
});

test("批改容忍加粗、换行和未知结论", () => {
  assert.equal(parseGrading("**【批改】正确**\n对").correct, true);
  assert.equal(parseGrading("【批改】\n正确\n理由").correct, true);
  assert.equal(parseGrading("【批改】正确率不高").correct, null);
  assert.equal(parseGrading("没有标记，只是一段话").correct, null);
});

test("缺批改标记时只做保守首行兜底", () => {
  assert.equal(parseGrading("你答对了，思路没问题").correct, true);
  assert.equal(parseGrading("回答错误，再想想").correct, false);
  const grading = parseGrading("这段没有明确结论");
  assert.equal(grading.found, false);
  assert.equal(grading.correct, null);
});

test("知识点解析容忍顿号/逗号与空项", () => {
  assert.deepEqual(parseKnowledge("【知识点】词汇、语音, 语法").names, ["词汇", "语音", "语法"]);
  assert.deepEqual(parseKnowledge("【知识点】").names, []);
  assert.equal(parseKnowledge("没有").found, false);
});

test("题干清理只删知识点行", () => {
  assert.equal(parseQuestionStem("A\nB\n【知识点】词汇"), "A\nB");
});

test("payload：答对也生成，缺判定为 null，空答案返回 null", () => {
  const grading = {found: true, correct: true, body: "对"};
  const payload = buildAttemptPayload({
    conversationId: 3, materialId: 2, questionNo: 1,
    question: "Q", answer: "A", grading, points: ["词汇"],
  });
  assert.equal(payload.conversation_id, 3);
  assert.equal(payload.material_id, 2);
  assert.equal(payload.question_no, 1);
  assert.equal(payload.correct, true);
  assert.deepEqual(payload.points, ["词汇"]);
  const unknown = buildAttemptPayload({
    question: "Q", answer: "A", grading: {found: false, correct: null, body: ""},
  });
  assert.equal(unknown.correct, null);
  assert.equal(buildAttemptPayload({question: "Q", answer: "  "}), null);
});

test("payload 最多带 3 个类目", () => {
  const payload = buildAttemptPayload({
    question: "Q", answer: "A", points: ["词汇", "语音", "语法", "阅读"],
  });
  assert.deepEqual(payload.points, ["词汇", "语音", "语法"]);
});
