// 写作页：今日 / 题库 / 历史、限时编辑器、批改轮询、二稿与错误卡。
import { api } from "../../api.js";
import { escapeHtml, relative, toast } from "../../ui.js";
import { createEditor } from "./editor.js";
import { feedbackHtml } from "./feedback.js";
import { MODE_LABEL, statusLabel } from "./format.js";
import { pollSubmission } from "./poll.js";

const KIND = "writing";

let panel = null;
let ctx = null;
let editor = null;
let poller = null;
let current = null;
let promptsCache = null;
let historyCache = null;
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
}

function subnav(active) {
  return `<div class="cet6-subnav">
    <button class="cet6-subtab${active === "home" ? " active" : ""}" type="button"
      data-act="view" data-view="home">今日</button>
    <button class="cet6-subtab${active === "library" ? " active" : ""}" type="button"
      data-act="view" data-view="library">题库</button>
    <button class="cet6-subtab${active === "history" ? " active" : ""}" type="button"
      data-act="view" data-view="history">历史</button>
  </div>`;
}

async function loadPrompts() {
  if (!promptsCache) {
    const data = await api.get("/api/cet6/train/prompts?kind=writing");
    promptsCache = data.items || [];
  }
  return promptsCache;
}

async function loadHistory() {
  if (!historyCache) {
    const data = await api.get("/api/cet6/train/submissions?kind=writing&limit=50");
    historyCache = data.items || [];
  }
  return historyCache;
}

function promptCard(item) {
  const meta = item.done
    ? `已练 ${item.done} 次 · 最近 ${item.last_band == null ? "—" : item.last_band} 档`
    : "还没练过";
  return `<button class="cet6-card" type="button" data-act="open-prompt" data-id="${escapeHtml(item.id)}">
    <span class="cet6-card-kicker">${escapeHtml(item.type || "")}</span>
    <strong>${escapeHtml(item.title)}</strong>
    <span class="cet6-card-meta">${escapeHtml(meta)}</span>
  </button>`;
}

async function renderHome() {
  view = "home";
  destroyEditor();
  clearPoll();
  panel.innerHTML = '<div class="empty">正在加载写作题库…</div>';
  try {
    const [prompts, history] = await Promise.all([loadPrompts(), loadHistory()]);
    const done = prompts.filter((item) => item.done > 0).length;
    const today = prompts.find((item) => !item.done)
      || [...prompts].sort((a, b) => (a.last_band ?? 15) - (b.last_band ?? 15))[0];
    const recent = history.slice(0, 5);
    const last = history.find((item) => item.band != null);
    panel.innerHTML = `${subnav("home")}
      <div class="cet6-hero">
        <div class="cet6-hero-main">
          <span class="cet6-kicker">今日写作</span>
          <h2>${escapeHtml(today?.title || "题库还没加载出来")}</h2>
          <p class="hint">${escapeHtml(today?.type || "")} · ${today?.minutes || 30} 分钟 ·
            目标 ${escapeHtml(String((today?.target_words || [150, 200]).join("–")))} 词</p>
          <div class="cet6-actions">
            <button class="btn btn-primary" type="button" data-act="start"
              data-id="${escapeHtml(today?.id || "w01")}" data-mode="timed">开始 30 分钟限时</button>
            <button class="btn" type="button" data-act="start"
              data-id="${escapeHtml(today?.id || "w01")}" data-mode="practice">练习模式</button>
            <button class="btn btn-small" type="button" data-act="view" data-view="library">看题库</button>
          </div>
        </div>
        <div class="cet6-hero-side">
          <div class="cet6-stat"><span>已练题目</span><strong>${done}/${prompts.length}</strong></div>
          <div class="cet6-stat"><span>最近档位</span><strong>${last?.band == null ? "—" : last.band}</strong></div>
          <div class="cet6-stat"><span>可复习错题</span><a href="#/wrongbook" data-act="go-wrongbook">去错题本</a></div>
        </div>
      </div>
      <div class="cet6-section-head"><h3>最近的练习</h3>
        <button class="btn btn-small" type="button" data-act="view" data-view="history">全部历史</button></div>
      ${recent.length ? `<div class="cet6-history">${recent.map(historyRow).join("")}</div>`
        : '<p class="hint">还没有提交过作文。先完成今天这篇。</p>'}`;
    ctx.setSub(`写作 · 题库 ${prompts.length} 题 · 已练 ${done} 题`);
  } catch (error) {
    panel.innerHTML = `<div class="empty"><strong>写作页没加载出来</strong>${escapeHtml(error.message)}</div>`;
  }
}

function historyRow(item) {
  const band = item.band == null ? "—" : item.band;
  return `<button class="cet6-history-row" type="button" data-act="open-sub" data-id="${item.id}">
    <span class="cet6-history-title">${escapeHtml(item.title || item.prompt_id)}</span>
    <span class="cet6-history-meta">${escapeHtml(MODE_LABEL[item.mode] || item.mode || "")} ·
      ${escapeHtml(statusLabel(item.status))} · ${escapeHtml(relative(item.updated_at))}</span>
    <span class="cet6-history-band${item.status === "reviewed" ? "" : " muted"}">${escapeHtml(String(band))}</span>
  </button>`;
}

async function renderLibrary() {
  view = "library";
  destroyEditor();
  clearPoll();
  panel.innerHTML = `${subnav("library")}<div class="empty">正在加载题库…</div>`;
  try {
    const prompts = await loadPrompts();
    panel.innerHTML = `${subnav("library")}
      <div class="cet6-grid">${prompts.map(promptCard).join("")}</div>
      <p class="hint">限时模式只给题目；练习模式额外给审题要点与分论点。两者都要提交后才有批改和范文。</p>`;
    ctx.setSub(`写作 · ${prompts.length} 题`);
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
    const prompt = await api.get(`/api/cet6/train/prompts/${encodeURIComponent(promptId)}?kind=writing`);
    panel.innerHTML = `${subnav("library")}
      <article class="cet6-prompt-detail">
        <span class="cet6-kicker">${escapeHtml(prompt.type || "")} · ${prompt.minutes || 30} 分钟 ·
          ${escapeHtml(String((prompt.target_words || [150, 200]).join("–")))} 词</span>
        <h2>${escapeHtml(prompt.title)}</h2>
        <p class="cet6-prompt-en">${escapeHtml(prompt.prompt_en || "")}</p>
        ${prompt.prompt_zh ? `<p class="hint">${escapeHtml(prompt.prompt_zh)}</p>` : ""}
        <div class="cet6-actions">
          <button class="btn btn-primary" type="button" data-act="start"
            data-id="${escapeHtml(prompt.id)}" data-mode="timed">开始限时</button>
          <button class="btn" type="button" data-act="start"
            data-id="${escapeHtml(prompt.id)}" data-mode="practice">练习模式</button>
          <button class="btn btn-small" type="button" data-act="view" data-view="library">返回题库</button>
        </div>
      </article>`;
    ctx.setSub(`写作 · ${prompt.title}`);
  } catch (error) {
    panel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

async function renderHistory() {
  view = "history";
  destroyEditor();
  clearPoll();
  panel.innerHTML = `${subnav("history")}<div class="empty">正在加载历史…</div>`;
  try {
    const rows = await loadHistory();
    panel.innerHTML = `${subnav("history")}
      ${rows.length ? `<div class="cet6-history">${rows.map(historyRow).join("")}</div>`
        : '<p class="hint">还没有提交记录。</p>'}`;
    ctx.setSub(`写作 · ${rows.length} 次提交`);
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
    submission, prompt,
    initialText: options.initialText || "",
    priorities: options.priorities || [],
    onSubmitted: (data) => showReviewing(submission.id, data),
    onBack: () => { invalidate(); renderHistory(); },
    onToast: (message, kind) => toast(message, kind),
  });
  panel.appendChild(editor.el);
  ctx.setSub(`写作 · ${submission.mode === "timed" ? "限时" : (submission.mode === "rewrite" ? "二稿" : "练习")}`);
}

async function startSubmission(promptId, mode) {
  try {
    const [prompt, submission] = await Promise.all([
      api.get(`/api/cet6/train/prompts/${encodeURIComponent(promptId)}?kind=writing`),
      api.post("/api/cet6/train/submissions", {
        kind: KIND, prompt_id: promptId, mode,
      }),
    ]);
    invalidate();
    renderEditor(submission, prompt);
  } catch (error) {
    toast(error.message || "没能开始写作", "err");
  }
}

function progressHtml(id, elapsed = 0) {
  return `<div class="cet6-progress">
    <div class="cet6-progress-mark">···</div>
    <h2>正在批改</h2>
    <p>三次评分取中位，通常 10 秒左右；关掉页面也会继续。</p>
    <p class="hint">已等待 ${elapsed} 秒</p>
    <div class="cet6-actions">
      <button class="btn btn-small" type="button" data-act="open-sub" data-id="${id}">刷新一下</button>
      <button class="btn btn-small" type="button" data-act="view" data-view="history">先看历史</button>
    </div>
  </div>`;
}

function showReviewing(id, initial) {
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
  panel.innerHTML = progressHtml(id, 0);
  poller = pollSubmission(id, {
    onTick: (seconds) => {
      const node = panel?.querySelector(".cet6-progress .hint");
      if (node) node.textContent = `已等待 ${seconds} 秒`;
    },
    onReviewed: (data) => renderFeedback(data),
    onFailed: (data) => renderFailed(data),
    onTimeout: () => {
      panel.innerHTML = `<div class="cet6-progress"><h2>还在批改</h2>
        <p>已经超过 3 分钟。可以稍后从「历史」打开这次提交。</p>
        <div class="cet6-actions"><button class="btn" type="button"
          data-act="view" data-view="history">回历史</button></div></div>`;
    },
    onError: (error) => {
      panel.innerHTML = `<div class="cet6-progress"><h2>查询失败</h2>
        <p>${escapeHtml(error.message)}</p>
        <div class="cet6-actions"><button class="btn" type="button"
          data-act="open-sub" data-id="${id}">重试</button></div></div>`;
    },
  });
}

function renderFeedback(detail) {
  view = "feedback";
  destroyEditor();
  clearPoll();
  invalidate();
  current = detail;
  panel.innerHTML = feedbackHtml(detail);
  ctx.setSub(`写作 · ${detail.title} · ${detail.band == null ? "已批改" : `${detail.band} 档`}`);
}

function renderFailed(detail) {
  view = "failed";
  destroyEditor();
  clearPoll();
  invalidate();
  current = detail;
  panel.innerHTML = `<div class="cet6-progress">
    <h2>批改没有完成</h2>
    <p class="cet6-warn">${escapeHtml(detail.error || "模型没有返回可用结果")}</p>
    <div class="cet6-actions">
      <button class="btn btn-primary" type="button" data-act="review-again" data-id="${detail.id}">重新批改</button>
      <button class="btn" type="button" data-act="edit" data-id="${detail.id}">改正文</button>
      <button class="btn btn-small" type="button" data-act="view" data-view="history">回历史</button>
    </div>
  </div>`;
}

function editorOptions(detail) {
  return detail.mode === "rewrite" && detail.parent
    ? { priorities: detail.parent.priorities || [] }
    : {};
}

async function openSubmission(id) {
  panel.innerHTML = '<div class="empty">正在打开这次提交…</div>';
  try {
    const detail = await api.get(`/api/cet6/train/submissions/${id}`);
    current = detail;
    if (detail.status === "reviewed") {
      renderFeedback(detail);
    } else if (detail.status === "reviewing") {
      showReviewing(id, detail);
    } else if (detail.status === "failed") {
      renderFailed(detail);
    } else {
      const prompt = await api.get(`/api/cet6/train/prompts/${encodeURIComponent(detail.prompt_id)}?kind=writing`);
      renderEditor(detail, prompt, editorOptions(detail));
    }
  } catch (error) {
    toast(error.message || "打开失败", "err");
  }
}

async function editSubmission(id) {
  try {
    const detail = await api.get(`/api/cet6/train/submissions/${id}`);
    const prompt = await api.get(`/api/cet6/train/prompts/${encodeURIComponent(detail.prompt_id)}?kind=writing`);
    renderEditor(detail, prompt, editorOptions(detail));
  } catch (error) {
    toast(error.message || "打开失败", "err");
  }
}

async function startRewrite(id) {
  try {
    const parent = current?.id === id ? current
      : await api.get(`/api/cet6/train/submissions/${id}`);
    const submission = await api.post("/api/cet6/train/submissions", {
      kind: KIND, prompt_id: parent.prompt_id, mode: "rewrite", parent_id: id,
    });
    invalidate();
    const prompt = await api.get(`/api/cet6/train/prompts/${encodeURIComponent(parent.prompt_id)}?kind=writing`);
    renderEditor(submission, prompt, {
      initialText: parent.text || "",
      priorities: parent.review?.priorities || [],
    });
  } catch (error) {
    toast(error.message || "开不了二稿", "err");
  }
}

async function reviewAgain(id) {
  try {
    const data = await api.post(`/api/cet6/train/submissions/${id}/review`, {});
    showReviewing(id, data);
  } catch (error) {
    toast(error.message || "重批失败", "err");
  }
}

async function addCard(index) {
  const error = current?.review?.errors?.[index];
  if (!error) return;
  try {
    const data = await api.post("/api/wrongbook", {
      source: "writing",
      question: `改错：${error.quote || ""}`,
      answer: error.fix || "",
      my_answer: error.quote || "",
      tags: error.type || "",
      note: error.why || "",
    });
    toast(data.created ? "已加入错题本" : "这条已经在错题本里", "ok");
  } catch (error_) {
    toast(error_.message || "加入失败", "err");
  }
}

async function saveScore(id) {
  const input = panel.querySelector("#cet6-score-input");
  const raw = input?.value?.trim() || "";
  try {
    const data = await api.post(
      `/api/cet6/train/submissions/${id}/external-score`,
      { score: raw === "" ? null : Number(raw) });
    renderFeedback(data);
    toast("已记录外部校准分", "ok");
  } catch (error) {
    toast(error.message || "分数没保存", "err");
  }
}

function onClick(event) {
  const target = event.target.closest("[data-act]");
  if (!target || !panel?.contains(target)) return;
  const act = target.dataset.act;
  if (act === "go-wrongbook") return;   // 交给浏览器跳 hash
  event.preventDefault();
  if (act === "back") {
    renderHistory();
  } else if (act === "view") {
    const next = target.dataset.view;
    if (next === "library") renderLibrary();
    else if (next === "history") renderHistory();
    else renderHome();
  } else if (act === "open-prompt") {
    renderPrompt(target.dataset.id);
  } else if (act === "start") {
    startSubmission(target.dataset.id, target.dataset.mode || "practice");
  } else if (act === "open-sub") {
    openSubmission(Number(target.dataset.id));
  } else if (act === "edit") {
    editSubmission(Number(target.dataset.id));
  } else if (act === "rewrite") {
    startRewrite(Number(target.dataset.id));
  } else if (act === "review-again") {
    reviewAgain(Number(target.dataset.id));
  } else if (act === "score") {
    saveScore(Number(target.dataset.id));
  } else if (act === "add-card") {
    addCard(Number(target.dataset.index));
  }
}

export async function mount(context) {
  panel = context.panel;
  ctx = context.ctx;
  panel.addEventListener("click", onClick);
  await renderHome();
  return () => {
    panel?.removeEventListener("click", onClick);
    clearPoll();
    destroyEditor();
    panel = null;
    ctx = null;
    current = null;
  };
}
