import assert from "node:assert/strict";
import { test } from "node:test";

import {
  TAB_NAMES, collectContext, contextLine, snapshotOf,
} from "../js/pages/cet6/ai-context.js";
import {
  translationContext, writingContext,
} from "../js/pages/cet6/cet6-contexts.js";

const base = {
  activeTab: "drill",
  tabNames: TAB_NAMES,
  selection: "",
  recentActions: ["提交听写"],
  provider: null,
};

test("通用上下文：九键齐全，来源固定六级", () => {
  const fields = collectContext(base);
  assert.equal(fields.surface, "cet6");
  assert.equal(fields.object_type, "cet6_tab");
  assert.equal(fields.object_id, "drill");
  assert.equal(fields.title, "六级训练 · 专项");
  assert.deepEqual(fields.provenance, { page: "cet6", tab: "drill" });
  assert.deepEqual(fields.recent_actions, ["提交听写"]);
});

test("页面 provider 覆盖对象事实，但不改 surface", () => {
  const fields = collectContext({
    ...base,
    provider: () => ({
      object_type: "cet6_dictation",
      object_id: "卷三|B|Passage 1|4",
      title: "第 3 句",
      surrounding: { 原句: "The thing is..." },
      learning_state: { 得分: "75%" },
    }),
  });
  assert.equal(fields.surface, "cet6");
  assert.equal(fields.object_type, "cet6_dictation");
  assert.equal(fields.title, "第 3 句");
  assert.equal(fields.surrounding["原句"], "The thing is...");
  assert.equal(fields.learning_state["得分"], "75%");
});

test("选中文字原样进快照，截断只由后端做", () => {
  const long = "字".repeat(5000);
  const snapshot = snapshotOf({ ...base, selection: long, provider: () => null });
  assert.equal(snapshot.selection.length, 5000);
  assert.equal(snapshot.surface, "cet6");
});

test("上下文摘要显示页面标题和选中提示", () => {
  const line = contextLine({
    ...base,
    selection: "这一句里的东西是什么",
    provider: () => ({ title: "六级专项听写 · 第 3 句" }),
  });
  assert.match(line, /六级专项听写 · 第 3 句/);
  assert.match(line, /已带选中「这一句里的东西是什么」/);
});

test("写作批改：带档位、原文和错误清单", () => {
  const fields = writingContext({
    editor: null,
    view: "feedback",
    panel: null,
    currentPrompt: null,
    current: {
      id: 9, title: "AI 与教育", band: 10, text: "My essay text.",
      review: {
        band_reason: "结构清楚但用词平",
        priorities: ["换掉重复的主语"],
        errors: [{ type: "搭配", quote: "make a progress", fix: "make progress" }],
      },
    },
  });
  assert.equal(fields.object_type, "cet6_writing_review");
  assert.equal(fields.title, "六级写作批改 · AI 与教育 · 10 档");
  assert.equal(fields.surrounding["我的原文"], "My essay text.");
  assert.match(fields.learning_state["错误清单"], /make progress/);
});

test("翻译单句：带原句、你的译文与参考译文", () => {
  const fields = translationContext({
    view: "sentence",
    panel: null,
    current: null,
    sentence: { id: "s12", zh: "教育是立国之本。", skill: "文化", source_title: "卷三" },
    sentenceResult: {
      review: {
        conclusion: "基本准确",
        reference: "Education is the foundation of a nation.",
        info_points: { covered: 2, total: 3 },
        must_fix: [{ quote: "is base of", fix: "is the foundation of" }],
      },
    },
  });
  assert.equal(fields.object_type, "cet6_translation_sentence");
  assert.equal(fields.surrounding["中文原句"], "教育是立国之本。");
  assert.equal(fields.surrounding["参考译文"], "Education is the foundation of a nation.");
  assert.equal(fields.learning_state["信息点"], "2 / 3");
});
