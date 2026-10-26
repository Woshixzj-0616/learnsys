import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cjkCount, clock, countWords, filterByField, initialEditorText,
  splitSentences, statusLabel,
} from "../js/pages/cet6/format.js";
import { feedbackHtml } from "../js/pages/cet6/feedback.js";

test("词数：撇号与连字符算一个词，中文不计", () => {
  assert.equal(countWords("It's a well-known fact."), 4);
  assert.equal(countWords("我在准备 CET-6 写作。"), 1);
  assert.equal(countWords(""), 0);
});

test("倒计时格式：补零、封底 00:00", () => {
  assert.equal(clock(0), "00:00");
  assert.equal(clock(59), "00:59");
  assert.equal(clock(60), "01:00");
  assert.equal(clock(-5), "00:00");
  assert.equal(clock(3599), "59:59");
});

test("中文字数与英文断句", () => {
  assert.equal(cjkCount("春节 abc 年夜饭"), 5);
  assert.equal(cjkCount("no chinese"), 0);
  assert.deepEqual(splitSentences("One. Two! Three?"), ["One.", "Two!", "Three?"]);
  assert.deepEqual(splitSentences("  One   sentence.  "), ["One sentence."]);
});

test("状态标签：未知状态原样返回", () => {
  assert.equal(statusLabel("reviewed"), "已批改");
  assert.equal(statusLabel("weird"), "weird");
  assert.equal(statusLabel(""), "未知");
});

function detail(overrides = {}) {
  return {
    id: 7, title: "大学生该不该做兼职", mode: "timed", text: "I learn many things.",
    word_count: 4, duration_s: 600, band: 12, external_score: null,
    updated_at: "2026-10-25 10:00:00",
    review: {
      band_label: "10–12 分", band_reason: "结构清楚。",
      stability: { bands: [11, 13, 12], spread: 2, stable: false },
      dimensions: { content: 3, structure: 3, language: 2, idiomatic: 1 },
      priorities: ["补例子", "检查冠词", "去掉 very"],
      rewrite_task: "只改搭配和冠词。",
      errors: [
        { type: "搭配", severity: "严重", quote: "learn many things",
          fix: "gain experience", why: "搭配不自然" },
        { type: "语法", severity: "一般", quote: "<script>bad</script>",
          fix: "bad", why: "转义测试" },
      ],
      cards: [{ question: "改错：learn many things" }],
      term_cards: [],
      hard_rules: { flags: [
        { code: "word_count", level: "严重", message: "只有 74 词，低于 140 词。" },
        { code: "paste", level: "一般", message: "检测到粘贴 25 个字符。" },
        { code: "left", level: "一般", message: "限时中离开页面 12 秒。" },
      ] },
    },
    ...overrides,
  };
}

test("批改视图：结构问题不进错题本，也不给手动收按钮", () => {
  const html = feedbackHtml(detail({
    review: {
      ...detail().review,
      errors: [
        { type: "结构", severity: "严重", quote: "whole essay", fix: "分三段",
          why: "没有分段" },
        { type: "搭配", severity: "一般", quote: "take shifts", fix: "work shifts",
          why: "搭配不地道" },
      ],
      cards: [],
    },
  }));
  assert.doesNotMatch(html, /已自动进错题本/);
  assert.match(html, /结构\/审题问题留在本次记录/);
  assert.match(html, /data-act="add-card" data-index="1"/);
});

test("批改视图：档位、不稳定提示、严重错误自动收录、普通错误可手动收", () => {
  const html = feedbackHtml(detail());
  assert.match(html, /13–15|10–12/);
  assert.match(html, /不稳定/);
  assert.match(html, /已自动进错题本/);
  assert.match(html, /data-act="add-card" data-index="1"/);
  assert.match(html, /&lt;script&gt;bad&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>bad<\/script>/);
  assert.match(html, /严重错误自动进错题本：<b>1<\/b>/);
  assert.match(html, /程序检查/);
  assert.match(html, /只有 74 词/);
  assert.match(html, /粘贴 25 个字符/);
  assert.match(html, /离开页面 12 秒/);
});

test("批改视图：复盘才展示范文；没有就不出现", () => {
  const withEssay = detail({
    model_essay: { text: "Paragraph one.\n\nParagraph two.", band: 14,
      notes: [{ paragraph: 1, note: "开头立场清楚" }] },
    upgrades: [{ low: "very good", high: "valuable", why: "更具体" }],
  });
  const html = feedbackHtml(withEssay);
  assert.match(html, /参考范文与升级对照/);
  assert.match(html, /开头立场清楚/);
  assert.match(html, /very good/);
  const plain = feedbackHtml(detail());
  assert.doesNotMatch(plain, /参考范文与升级对照/);
});

test("翻译复盘：逐句对照三列、信息点与术语卡", () => {
  const html = feedbackHtml(detail({
    kind: "translation",
    text: "Spring Festival is important. Families eat together.",
    segments: [
      { zh: "春节很重要。", reference: "The Spring Festival is important.",
        info_points: ["ip1"] },
      { zh: "家人一起吃饭。", reference: "Families eat together.",
        info_points: ["ip2"] },
    ],
    reference: "The Spring Festival is important. Families eat together.",
    info_point_table: [
      { id: "ip1", zh: "春节重要" }, { id: "ip2", zh: "家人吃饭" },
    ],
    terms: [{ zh: "春节", en: "the Spring Festival", note: "专有名词" }],
    review: {
      ...detail().review,
      alignment: [
        { segment: 1, quote: "Spring Festival is important." },
        { segment: 2, quote: "Families eat together." },
      ],
    },
  }));
  assert.match(html, /逐句对照/);
  assert.match(html, /中文原句/);
  assert.match(html, /我的译文/);
  assert.match(html, /参考译文/);
  assert.match(html, /信息点：家人吃饭/);
  assert.match(html, /data-act="add-term"/);
  assert.match(html, /春节/);
});

test("批改视图：翻译信息点漏译", () => {
  const html = feedbackHtml(detail({
    kind: "translation", mode: "practice",
    review: {
      ...detail().review,
      info_points: { total: 10, covered: 7, missing_points: ["春节起源", "年夜饭"],
        notes: "漏掉两层意思。" },
    },
  }));
  assert.match(html, /7 \/ 10/);
  assert.match(html, /漏译：春节起源、年夜饭/);
  assert.match(html, /漏掉两层意思/);
});

test("编辑器初始文本：二稿 > 草稿 > 首句预填 > 空", () => {
  const lead = "Although cities grow, nature still matters.";
  assert.equal(initialEditorText({
    initialText: "rewrite", submissionText: "", mode: "rewrite", leadSentence: lead,
  }), "rewrite");
  assert.equal(initialEditorText({
    submissionText: "draft text", mode: "practice", leadSentence: lead,
  }), "draft text");
  assert.equal(initialEditorText({
    mode: "practice", leadSentence: lead,
  }), `${lead}\n\n`);
  assert.equal(initialEditorText({
    mode: "rewrite", leadSentence: lead,
  }), "");
  assert.equal(initialEditorText({ mode: "practice" }), "");
});

test("题库筛选：空值全部、命中、无命中", () => {
  const rows = [
    { id: "w13", type: "首句续写" }, { id: "w19", type: "首句续写" },
    { id: "w01", type: "观点论证" },
  ];
  assert.equal(filterByField(rows, "type", "").length, 3);
  assert.deepEqual(
    filterByField(rows, "type", "首句续写").map((row) => row.id),
    ["w13", "w19"]);
  assert.deepEqual(filterByField(rows, "type", "不存在"), []);
  assert.deepEqual(filterByField(null, "type", "x"), []);
});
