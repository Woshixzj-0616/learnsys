// 翻译页：一句一译（默认）、整段限时、术语卡、逐句对照、历史。
// 数据缓存在 translation-data.js，提交状态机在 translation-flow.js；
// 这里负责页面状态、视图装配与事件分发。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";
import { createEditor } from "./editor.js";
import { feedbackHtml } from "./feedback.js";
import {
  addCard, addTerm, reviewAgain, saveScore, startRewrite,
} from "./translation-actions.js";
import { openDeepLink } from "./deep-link.js";
import {
  failedHtml, historyHtml, homeHtml, libraryHtml, promptViewHtml,
  sentenceAttemptHtml, sentenceHintsHtml, sentenceResultHtml,
  sentenceViewHtml, termsHtml,
} from "./translation-views.js";
import { clearContextProvider, setContextProvider } from "./ai.js";
import { translationContext } from "./cet6-contexts.js";
import {
  invalidate, loadHistory, loadPrompts, loadSentences, loadTerms,
  pickSentence, sentencesCache,
} from "./translation-data.js";
import {
  editSubmission, openSubmission, showWholeReviewing, startWhole, submitSentence,
} from "./translation-flow.js";

let panel = null;
let ctx = null;
let editor = null;
let poller = null;
let current = null;
let historyMode = "whole";
let sentence = null;
let sentenceResult = null;
let sentenceSkill = "";
let hintLevel = 0;
let view = "home";

// 给六级 AI 抽屉：一句一译的当前句/批改结论，或整段批改结果；模板在 cet6-contexts.js。
export function context() {
  return translationContext({ view, current, sentence, sentenceResult, panel });
}

function clearPoll() {
  if (poller) {
    poller.stop();
    poller = null;
  }
}

function destroyEditor() {
  if (editor) {
    try { editor.stop(); } catch { /* 忽略 */ }
    editor = null;
  }
}

// translation-flow.js 只认这个接口：状态读写 + 页面渲染回调，避免反向依赖本文件。
const page = {
  panel: null,
  ctx: null,
  get current() { return current; },
  set current(value) { current = value; },
  get poller() { return poller; },
  set poller(value) { poller = value; },
  get sentence() { return sentence; },
  set sentence(value) { sentence = value; },
  get sentenceResult() { return sentenceResult; },
  set sentenceResult(value) { sentenceResult = value; },
  get view() { return view; },
  set view(value) { view = value; },
  destroyEditor,
  clearPoll,
  renderEditor: (...args) => renderEditor(...args),
  renderFeedback: (...args) => renderFeedback(...args),
  renderFailed: (...args) => renderFailed(...args),
};

async function renderHome() {
  view = "home";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在加载翻译训练…</div>';
  try {
    const [prompts, history, sentences] = await Promise.all([
      loadPrompts(), loadHistory("whole"), loadSentences()]);
    const done = prompts.filter((row) => row.done > 0).length;
    const todayPrompt = prompts.find((row) => !row.done) || prompts[0];
    const todaySentence = pickSentence("", sentence?.id);
    const recent = history.slice(0, 5);
    const last = history.find((row) => row.band != null);
    panel.innerHTML = homeHtml({
      prompts, todayPrompt, todaySentence, recent, last,
      attemptedCount: sentences.attempted_count,
    });
    ctx.setSub(`翻译 · 一句一译 · 单句已练 ${sentences.attempted_count || 0}`);
  } catch (error) {
    panel.innerHTML = `<div class="empty"><strong>翻译页没加载出来</strong>${escapeHtml(error.message)}</div>`;
  }
}

async function renderSentence(skill = sentenceSkill, options = {}) {
  view = "sentence";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在挑一句…</div>';
  try {
    await loadSentences();
    sentenceSkill = skill || "";
    // 从历史进来时锁定那一句，并把上次译文填回输入框。
    const cache = sentencesCache();
    const target = options.id
      ? (cache?.items || []).find((row) => row.id === options.id)
      : null;
    sentence = target || pickSentence(sentenceSkill, sentence?.id);
    sentenceResult = null;
    hintLevel = 0;
    if (!sentence) {
      panel.innerHTML = '<div class="empty">这句题库空了。</div>';
      return;
    }
    panel.innerHTML = sentenceViewHtml({
      sentence, skills: cache.skills || [], skill: sentenceSkill,
      attemptedCount: cache.attempted_count, hintLevel,
      resultHtml: sentenceResult ? sentenceResultHtml(sentenceResult) : "",
    });
    if (options.prefill) {
      const textarea = panel.querySelector("#cet6-sentence-text");
      if (textarea) textarea.value = options.prefill;
    }
    ctx.setSub(`翻译 · 一句一译 · ${sentence.skill || ""}`);
  } catch (error) {
    panel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

async function renderLibrary() {
  view = "library";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在加载题库…</div>';
  try {
    const prompts = await loadPrompts();
    panel.innerHTML = libraryHtml(prompts);
    ctx.setSub(`翻译 · 题库 ${prompts.length} 篇`);
  } catch (error) {
    panel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

async function renderPrompt(promptId) {
  view = "prompt";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在打开题目…</div>';
  try {
    const prompt = await api.get(
      `/api/cet6/train/prompts/${encodeURIComponent(promptId)}?kind=translation`);
    panel.innerHTML = promptViewHtml(prompt);
    ctx.setSub(`翻译 · ${prompt.title}`);
  } catch (error) {
    panel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

function renderEditor(submission, prompt, options = {}) {
  destroyEditor();
  clearPoll();
  current = submission;
  panel.innerHTML = "";
  editor = createEditor({
    submission, prompt, kind: "translation",
    initialText: options.initialText || "",
    onSubmitted: (data) => showWholeReviewing(page, submission.id, data),
    onBack: () => { invalidate(); renderHistory(); },
    onToast: (message, kind) => toast(message, kind),
  });
  panel.appendChild(editor.el);
  ctx.setSub(`翻译 · ${submission.mode === "timed" ? "限时" : "练习"}`);
}

function renderFeedback(detail) {
  view = "feedback";
  destroyEditor();
  clearPoll();
  invalidate();
  current = detail;
  panel.innerHTML = feedbackHtml(detail);
  ctx.setSub(`翻译 · ${detail.title} · ${detail.band == null ? "已批改" : `${detail.band} 档`}`);
}

function renderFailed(detail) {
  view = "failed";
  destroyEditor();
  clearPoll();
  current = detail;
  panel.innerHTML = failedHtml(detail);
}

async function renderHistory(mode = historyMode) {
  view = "history";
  historyMode = mode === "sentence" ? "sentence" : "whole";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在加载历史…</div>';
  try {
    const rows = await loadHistory(historyMode);
    panel.innerHTML = historyHtml(rows, historyMode);
    ctx.setSub(historyMode === "sentence"
      ? `翻译 · 一句一译 ${rows.length} 次`
      : `翻译 · ${rows.length} 次整篇提交`);
  } catch (error) {
    panel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

async function openSentenceAttempt(id) {
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在打开这次提交…</div>';
  try {
    const detail = await api.get(`/api/cet6/train/submissions/${id}`);
    if (!detail.sentence) throw new Error("这一条没有单句题目信息");
    current = detail;
    view = "sentence-attempt";
    panel.innerHTML = sentenceAttemptHtml(detail);
    ctx.setSub(`翻译 · 一句一译 · ${detail.sentence.skill || ""}`);
  } catch (error) {
    toast(error.message || "打开失败", "err");
    renderHistory("sentence");
  }
}

async function renderTerms() {
  view = "terms";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在加载术语…</div>';
  try {
    const terms = await loadTerms();
    panel.innerHTML = termsHtml(terms);
    ctx.setSub(`翻译 · 术语卡 ${terms.length} 张`);
  } catch (error) {
    panel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

function onInput(event) {
  if (event.target?.id !== "cet6-term-search") return;
  const needle = String(event.target.value || "").trim().toLowerCase();
  for (const row of panel.querySelectorAll(".cet6-term-row")) {
    row.hidden = Boolean(needle) && !row.dataset.search?.includes(needle);
  }
}

function onChange(event) {
  if (event.target?.id === "cet6-skill") renderSentence(event.target.value);
}

function onClick(event) {
  const target = event.target.closest("[data-act]");
  if (!target || !panel?.contains(target)) return;
  const act = target.dataset.act;
  if (act === "go-wrongbook") return;
  event.preventDefault();
  if (act === "back") {
    renderHistory();
  } else if (act === "view") {
    const next = target.dataset.view;
    if (next === "sentence") renderSentence();
    else if (next === "library") renderLibrary();
    else if (next === "terms") renderTerms();
    else if (next === "history") renderHistory();
    else renderHome();
  } else if (act === "open-prompt") {
    renderPrompt(target.dataset.id);
  } else if (act === "start-whole") {
    startWhole(page, target.dataset.id, target.dataset.mode || "practice");
  } else if (act === "history-mode") {
    renderHistory(target.dataset.mode);
  } else if (act === "open-sub") {
    openSubmission(page, Number(target.dataset.id));
  } else if (act === "open-sentence-sub") {
    openSentenceAttempt(Number(target.dataset.id));
  } else if (act === "sentence-practice") {
    renderSentence("", { id: target.dataset.id, prefill: current?.text || "" });
  } else if (act === "edit") {
    editSubmission(page, Number(target.dataset.id));
  } else if (act === "sentence-submit") {
    submitSentence(page);
  } else if (act === "sentence-next") {
    renderSentence(sentenceSkill);
  } else if (act === "sentence-next-skill") {
    renderSentence(sentence?.skill || "");
  } else if (act === "sentence-retry") {
    sentenceResult = null;
    hintLevel = 0;
    const textarea = panel.querySelector("#cet6-sentence-text");
    if (textarea) textarea.value = "";
    const box = panel.querySelector("#cet6-sentence-result");
    if (box) box.innerHTML = "";
    const hints = panel.querySelector(".cet6-sentence-hints");
    if (hints) hints.remove();
    const second = panel.querySelector('[data-act="sentence-hint-2"]');
    if (second) second.disabled = true;
    toast("再译一遍：对比刚才的必改项", "ok");
  } else if (act === "sentence-hint-1") {
    hintLevel = Math.max(hintLevel, 1);
    renderSentenceHints();
  } else if (act === "sentence-hint-2") {
    hintLevel = 2;
    renderSentenceHints();
  } else if (act === "add-term") {
    addTerm(target);
  } else if (act === "add-card") {
    addCard(current, Number(target.dataset.index));
  } else if (act === "rewrite") {
    startRewrite({ current, renderEditor, invalidate, id: Number(target.dataset.id) });
  } else if (act === "review-again") {
    reviewAgain({
      showWholeReviewing: (id, data) => showWholeReviewing(page, id, data),
      id: Number(target.dataset.id),
    });
  } else if (act === "score") {
    saveScore({ panel, renderFeedback, id: Number(target.dataset.id) });
  }
}

function renderSentenceHints() {
  const card = panel.querySelector(".cet6-sentence-card");
  if (!card) return;
  const old = card.querySelector(".cet6-sentence-hints");
  if (old) old.remove();
  const source = card.querySelector(".cet6-source-zh");
  if (source) source.insertAdjacentHTML("afterend", sentenceHintsHtml());
  const second = card.querySelector('[data-act="sentence-hint-2"]');
  if (second) second.disabled = hintLevel < 1;
}

export async function mount(options) {
  panel = options.panel;
  ctx = options.ctx;
  page.panel = panel;
  page.ctx = ctx;
  panel.addEventListener("click", onClick);
  panel.addEventListener("input", onInput);
  panel.addEventListener("change", onChange);
  setContextProvider(context);
  await renderHome();
  await openDeepLink({ ctx, tab: "translation",
    openSubmission: (id) => openSubmission(page, id), renderSentence,
    startRewrite: (id) => current?.mode === "rewrite" ? undefined
      : startRewrite({ current, renderEditor, invalidate, id }) });
  return () => {
    panel?.removeEventListener("click", onClick);
    panel?.removeEventListener("input", onInput);
    panel?.removeEventListener("change", onChange);
    clearContextProvider();
    clearPoll();
    destroyEditor();
    panel = null;
    ctx = null;
    page.panel = null;
    page.ctx = null;
    current = null;
    sentence = null;
    sentenceResult = null;
  };
}
