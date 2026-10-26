// 翻译页：一句一译（默认）、整段限时、术语卡、逐句对照、历史。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";
import { createEditor } from "./editor.js";
import { feedbackHtml } from "./feedback.js";
import { pollSubmission } from "./poll.js";
import {
  addCard, addTerm, reviewAgain, saveScore, startRewrite,
} from "./translation-actions.js";
import {
  failedHtml, historyHtml, homeHtml, libraryHtml, progressHtml,
  promptViewHtml, sentenceHintsHtml, sentenceResultHtml, sentenceViewHtml,
  termsHtml,
} from "./translation-views.js";

const KIND = "translation";

let panel = null;
let ctx = null;
let editor = null;
let poller = null;
let current = null;
let promptsCache = null;
let historyCache = null;
let termsCache = null;
let sentenceCache = null;
let sentence = null;
let sentenceResult = null;
let sentenceSkill = "";
let hintLevel = 0;
let view = "home";

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

function invalidate() {
  promptsCache = null;
  historyCache = null;
  sentenceCache = null;
}

async function loadPrompts() {
  if (!promptsCache) {
    const data = await api.get("/api/cet6/train/prompts?kind=translation");
    promptsCache = data.items || [];
  }
  return promptsCache;
}

async function loadHistory() {
  if (!historyCache) {
    const data = await api.get("/api/cet6/train/submissions?kind=translation&limit=50");
    historyCache = data.items || [];
  }
  return historyCache;
}

async function loadTerms(packId = "") {
  const key = packId || "*";
  if (!termsCache || termsCache.key !== key) {
    const data = await api.get(
      `/api/cet6/train/terms${packId ? `?pack_id=${encodeURIComponent(packId)}` : ""}`);
    termsCache = { key, items: data.items || [] };
  }
  return termsCache.items;
}

async function loadSentences() {
  if (!sentenceCache) {
    const data = await api.get("/api/cet6/train/sentences?limit=200");
    sentenceCache = data;
  }
  return sentenceCache;
}

function pickSentence(skill) {
  const pool = (sentenceCache?.items || []).filter(
    (row) => !skill || row.skill === skill);
  return pool.find((row) => !row.attempted)
    || pool.find((row) => row.id !== sentence?.id)
    || pool[0] || null;
}

async function renderHome() {
  view = "home";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在加载翻译训练…</div>';
  try {
    const [prompts, history, sentences] = await Promise.all([
      loadPrompts(), loadHistory(), loadSentences()]);
    const done = prompts.filter((row) => row.done > 0).length;
    const todayPrompt = prompts.find((row) => !row.done) || prompts[0];
    const todaySentence = pickSentence("");
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

async function renderSentence(skill = sentenceSkill) {
  view = "sentence";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在挑一句…</div>';
  try {
    await loadSentences();
    sentenceSkill = skill || "";
    sentence = pickSentence(sentenceSkill);
    sentenceResult = null;
    hintLevel = 0;
    if (!sentence) {
      panel.innerHTML = '<div class="empty">这句题库空了。</div>';
      return;
    }
    panel.innerHTML = sentenceViewHtml({
      sentence, skills: sentenceCache.skills || [], skill: sentenceSkill,
      attemptedCount: sentenceCache.attempted_count, hintLevel,
      resultHtml: sentenceResult ? sentenceResultHtml(sentenceResult) : "",
    });
    ctx.setSub(`翻译 · 一句一译 · ${sentence.skill || ""}`);
  } catch (error) {
    panel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

async function submitSentence() {
  const textarea = panel.querySelector("#cet6-sentence-text");
  const text = textarea?.value?.trim() || "";
  if (!text) {
    toast("先写一句英文再提交", "err");
    return;
  }
  const box = panel.querySelector("#cet6-sentence-result");
  box.innerHTML = '<p class="hint">正在审核…</p>';
  try {
    const data = await api.post(
      `/api/cet6/train/sentences/${encodeURIComponent(sentence.id)}/review`,
      { text, pasted_chars: 0, left_seconds: 0 });
    sentenceResult = data;
    if (sentenceCache) {
      sentence.attempted = true;
      const row = sentenceCache.items.find((item) => item.id === sentence.id);
      if (row) row.attempted = true;
      sentenceCache.attempted_count = (sentenceCache.attempted_count || 0) + 1;
    }
    box.innerHTML = sentenceResultHtml(data);
    ctx.setSub(`翻译 · 一句一译 · ${sentence.skill || ""}`);
  } catch (error) {
    box.innerHTML = `<p class="cet6-warn">${escapeHtml(error.message || "审核失败")}</p>`;
  }
}

function sentenceNext(sameSkill) {
  renderSentence(sameSkill ? sentence?.skill || "" : sentenceSkill);
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
    onSubmitted: (data) => showWholeReviewing(submission.id, data),
    onBack: () => { invalidate(); renderHistory(); },
    onToast: (message, kind) => toast(message, kind),
  });
  panel.appendChild(editor.el);
  ctx.setSub(`翻译 · ${submission.mode === "timed" ? "限时" : "练习"}`);
}

async function startWhole(promptId, mode) {
  try {
    const [prompt, submission] = await Promise.all([
      api.get(`/api/cet6/train/prompts/${encodeURIComponent(promptId)}?kind=translation`),
      api.post("/api/cet6/train/submissions", {
        kind: KIND, prompt_id: promptId, mode,
      }),
    ]);
    invalidate();
    renderEditor(submission, prompt);
  } catch (error) {
    toast(error.message || "没能开始翻译", "err");
  }
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

function showWholeReviewing(id, initial) {
  destroyEditor();
  clearPoll();
  invalidate();
  const handle = (data) => {
    if (data.status === "reviewed") {
      renderFeedback(data);
      return true;
    }
    if (data.status === "failed") {
      renderFailed(data);
      return true;
    }
    return false;
  };
  view = "review";
  if (handle(initial)) return;
  panel.innerHTML = progressHtml(id);
  poller = pollSubmission(id, {
    onTick: (seconds) => {
      const node = panel?.querySelector(".cet6-progress .hint");
      if (node) node.textContent = `已等待 ${seconds} 秒`;
    },
    onReviewed: (data) => renderFeedback(data),
    onFailed: (data) => renderFailed(data),
    onTimeout: () => {
      panel.innerHTML = '<div class="cet6-progress"><h2>还在批改</h2><p>稍后从「历史」打开这次提交。</p></div>';
    },
    onError: (error) => {
      panel.innerHTML = `<div class="cet6-progress"><h2>查询失败</h2>
        <p>${escapeHtml(error.message)}</p>
        <div class="cet6-actions"><button class="btn" type="button"
          data-act="open-sub" data-id="${id}">重试</button></div></div>`;
    },
  });
}

async function openSubmission(id) {
  panel.innerHTML = '<div class="empty">正在打开这次提交…</div>';
  try {
    const detail = await api.get(`/api/cet6/train/submissions/${id}`);
    current = detail;
    if (detail.status === "reviewed") {
      renderFeedback(detail);
    } else if (detail.status === "reviewing") {
      showWholeReviewing(id, detail);
    } else if (detail.status === "failed") {
      renderFailed(detail);
    } else {
      const prompt = await api.get(
        `/api/cet6/train/prompts/${encodeURIComponent(detail.prompt_id)}?kind=translation`);
      renderEditor(detail, prompt);
    }
  } catch (error) {
    toast(error.message || "打开失败", "err");
  }
}

async function editSubmission(id) {
  try {
    const detail = await api.get(`/api/cet6/train/submissions/${id}`);
    const prompt = await api.get(
      `/api/cet6/train/prompts/${encodeURIComponent(detail.prompt_id)}?kind=translation`);
    renderEditor(detail, prompt);
  } catch (error) {
    toast(error.message || "打开失败", "err");
  }
}

async function renderHistory() {
  view = "history";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在加载历史…</div>';
  try {
    const rows = await loadHistory();
    panel.innerHTML = historyHtml(rows);
    ctx.setSub(`翻译 · ${rows.length} 次整篇提交`);
  } catch (error) {
    panel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
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
    startWhole(target.dataset.id, target.dataset.mode || "practice");
  } else if (act === "open-sub") {
    openSubmission(Number(target.dataset.id));
  } else if (act === "edit") {
    editSubmission(Number(target.dataset.id));
  } else if (act === "sentence-submit") {
    submitSentence();
  } else if (act === "sentence-next") {
    sentenceNext(false);
  } else if (act === "sentence-next-skill") {
    sentenceNext(true);
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
    reviewAgain({ showWholeReviewing, id: Number(target.dataset.id) });
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

export async function mount(context) {
  panel = context.panel;
  ctx = context.ctx;
  panel.addEventListener("click", onClick);
  panel.addEventListener("input", onInput);
  panel.addEventListener("change", onChange);
  await renderHome();
  return () => {
    panel?.removeEventListener("click", onClick);
    panel?.removeEventListener("input", onInput);
    panel?.removeEventListener("change", onChange);
    clearPoll();
    destroyEditor();
    panel = null;
    ctx = null;
    current = null;
  };
}
