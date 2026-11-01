import assert from "node:assert/strict";
import { test } from "node:test";

import {
  historyHtml, sentenceAttemptHtml,
} from "../js/pages/cet6/translation-views.js";

test("历史：整篇与单句两段切换、空态文案分开", () => {
  const whole = historyHtml([], "whole");
  assert.match(whole, /data-act="history-mode" data-mode="whole"/);
  assert.match(whole, /data-act="history-mode" data-mode="sentence"/);
  assert.match(whole, /还没有整篇翻译提交/);

  const single = historyHtml([], "sentence");
  assert.match(single, /还没有一句一译记录/);
});

test("历史：单句行带结论、点开走单句详情，用户译文要转义", () => {
  const html = historyHtml([{
    id: 1, prompt_id: "x001", title: "中文原句", skill: "断句意群",
    conclusion: "有偏差", preview: "<script>alert(1)</script>",
    updated_at: "2026-10-31 22:37:38", status: "reviewed", mode: "sentence",
  }], "sentence");
  assert.match(html, /data-act="open-sentence-sub" data-id="1"/);
  assert.match(html, /有偏差/);
  assert.match(html, /cet6-history-conclusion warn/);
  assert.ok(!html.includes("<script>"), "预览必须转义");
});

test("单句历史详情：原句 + 上次译文 + 再译这一句", () => {
  const html = sentenceAttemptHtml({
    id: 7, prompt_id: "x001", text: "My first try.",
    updated_at: "2026-10-31 22:37:38",
    sentence: { id: "x001", zh: "随着城市人口增长…", skill: "断句意群" },
    review: {
      conclusion: "基本准确", info_points: { covered: 1, total: 2 },
      must_fix: [], suggestions: [], reference: "As the population grows…",
    },
  });
  assert.match(html, /随着城市人口增长/);
  assert.match(html, /My first try\./);
  assert.match(html, /data-act="sentence-practice"[\s\S]*data-id="x001"/);
  assert.match(html, /As the population grows/);
  assert.match(html, /第 7 次提交/);
});
