// 六级训练通用 AI 助手：右下角圆圈 + 右侧抽屉（对话 / 历史）。
// 用法对齐精听工作台：自动带当前页面上下文；选中文字可以直接问。
// 会话统一走 module=cet6，与 iframe 里的精听 AI 共享同一批历史，不新增后端接口。
import { api, streamChat, stopChat } from "../../api.js";
import { escapeHtml } from "../../ui.js";
import { TAB_NAMES, contextLine, safeProvider, snapshotOf } from "./ai-context.js";
import { installFloating } from "./ai-floating.js";
import {
  FALLBACK_SUGGESTS, SUGGESTS, addMessage, buildDom, paintBubble,
  renderHistory, renderSuggest, renderWelcome, status,
} from "./ai-view.js";

const CONV_KEY = "learnsys_cet6_ai_conv";

let host = null;
let nodes = null;
let floating = null;
let enabled = true;
let activeTab = "listening";
let provider = null;
let pendingSelection = "";
let conversationId = readNumber(CONV_KEY);
let streaming = false;
let abort = null;
let runId = "";
let loaded = false;
let historyRows = [];
let historyQuery = "";
let historyLoading = false;
let recentActions = [];
let activeView = "chat";
let observer = null;
let contextPending = false;
const bindings = [];

function readNumber(key) {
  try { return Number(localStorage.getItem(key)) || 0; } catch { return 0; }
}

function saveNumber(key, value) {
  try { localStorage.setItem(key, String(Number(value) || 0)); } catch { /* 忽略 */ }
}

function on(target, type, fn, options) {
  target.addEventListener(type, fn, options);
  bindings.push(() => target.removeEventListener(type, fn, options));
}

function shorten(text, limit = 24) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

function scrollBottom() {
  if (nodes?.messages) nodes.messages.scrollTop = nodes.messages.scrollHeight;
}

// ---- 上下文 ----

function refreshContext() {
  if (!nodes?.ctx) return;
  const next = contextLine({
    activeTab, tabNames: TAB_NAMES, selection: pendingSelection, provider,
  });
  if (nodes.ctx.textContent !== next) nodes.ctx.textContent = next;
}

// 抽屉打开时盯着页面 DOM：切子视图或翻到下一题后，「正在看」跟着变。
// 和 refreshContext 的「不同才写」配合，避免自己的写入又触发自己。
function watchContext() {
  if (observer || !host) return;
  observer = new MutationObserver(() => {
    if (contextPending) return;
    contextPending = true;
    setTimeout(() => {
      contextPending = false;
      refreshContext();
    }, 150);
  });
  observer.observe(host, { childList: true, subtree: true, characterData: true });
}

function stopWatching() {
  observer?.disconnect();
  observer = null;
}

function note(text) {
  const value = String(text || "").trim();
  if (!value) return;
  recentActions.push(value);
  if (recentActions.length > 20) recentActions = recentActions.slice(-20);
}

// ---- 对话渲染 ----

function welcome() {
  if (!nodes) return;
  renderWelcome(nodes.messages);
  renderSuggest(nodes.suggest, SUGGESTS[activeTab] || FALLBACK_SUGGESTS);
  refreshContext();
  scrollBottom();
}

function paint(target, state, isStreaming) {
  paintBubble(target.bubble, state, isStreaming);
}

function setStreaming(next) {
  streaming = !!next;
  if (!nodes) return;
  nodes.send.hidden = streaming;
  nodes.stop.hidden = !streaming;
}

function syncView() {
  if (!nodes) return;
  for (const button of nodes.dock.querySelectorAll("[data-ai-tab]")) {
    button.classList.toggle("on", button.dataset.aiTab === activeView);
  }
  nodes.chatView.hidden = activeView !== "chat";
  nodes.historyView.hidden = activeView !== "history";
  if (activeView === "history") loadHistory();
}

function showView(view) {
  activeView = view === "history" ? "history" : "chat";
  syncView();
  if (activeView === "chat") {
    refreshContext();
    scrollBottom();
    nodes?.input?.focus();
  }
}

// ---- 会话 ----

function setConversation(id) {
  conversationId = Number(id) || 0;
  saveNumber(CONV_KEY, conversationId);
}

function storedText(content) {
  if (content == null) return "";
  if (typeof content === "string") return content;
  return String(content.text || "");
}

function renderStored(message) {
  const content = message.content || {};
  if (message.role === "user") {
    const text = storedText(content);
    if (text) addMessage(nodes.messages, "user", text);
    return;
  }
  if (message.role !== "assistant") return;
  const error = typeof content === "object" ? String(content.error || "") : "";
  if (error) {
    addMessage(nodes.messages, "error", `上次回答出错：${error}`);
    return;
  }
  const text = storedText(content);
  const thinking = typeof content === "object" ? String(content.thinking || "") : "";
  if (!text) return;
  const target = addMessage(nodes.messages, "assistant", "");
  paint(target, { answer: text, thinking, trace: [], error: "" }, false);
}

async function loadConversation(id) {
  id = Number(id) || 0;
  if (!id) {
    welcome();
    return;
  }
  nodes.messages.innerHTML = status("正在读取对话…");
  try {
    const data = await api.get(`/api/conversations/${id}`);
    nodes.messages.innerHTML = "";
    (data.messages || []).forEach(renderStored);
    if (!(data.messages || []).length) welcome();
    setConversation(data.id || id);
    refreshContext();
    scrollBottom();
  } catch (error) {
    nodes.messages.innerHTML = "";
    addMessage(nodes.messages, "error", `读取对话失败：${error.message || error}`);
  }
}

function renderHistoryNow() {
  if (!nodes?.historyList) return;
  renderHistory(nodes.historyList, historyRows, historyQuery, conversationId);
}

async function loadHistory() {
  if (historyLoading || !nodes) return;
  historyLoading = true;
  nodes.historyList.innerHTML = status("正在翻历史…");
  try {
    const data = await api.get("/api/conversations?limit=50&module=cet6");
    historyRows = Array.isArray(data.items) ? data.items : [];
    renderHistoryNow();
  } catch (error) {
    nodes.historyList.innerHTML =
      `<p class="cet6-ai-status">历史读取失败：${escapeHtml(error.message || error)}</p>`;
  } finally {
    historyLoading = false;
  }
}

async function openConversation(id) {
  if (streaming) await stop();
  showView("chat");
  await loadConversation(id);
}

function newConversation() {
  if (streaming) stop();
  setConversation(0);
  loaded = true;
  pendingSelection = "";
  nodes.messages.innerHTML = "";
  welcome();
  showView("chat");
  nodes.input.focus();
}

// ---- 发送 ----

async function send() {
  if (streaming || !nodes) return;
  const message = String(nodes.input.value || "").trim();
  if (!message) return;
  nodes.input.value = "";
  addMessage(nodes.messages, "user", message);
  const target = addMessage(nodes.messages, "assistant", "");
  const state = { answer: "", thinking: "", trace: [], error: "" };
  paint(target, state, true);

  note(`提问：${shorten(message, 60)}`);
  let payload;
  try {
    payload = snapshotOf({
      activeTab, tabNames: TAB_NAMES,
      selection: pendingSelection, recentActions, provider,
    });
  } catch (error) {
    state.error = error.message || "上下文没组装好";
    paint(target, state, false);
    return;
  }

  const controller = new AbortController();
  abort = controller;
  runId = "";
  setStreaming(true);

  const onEvent = (event) => {
    const kind = event.kind;
    const data = event.data || {};
    if (kind === "start") {
      if (data.conversation_id) setConversation(data.conversation_id);
      if (data.run_id) runId = String(data.run_id);
      if (data.model && nodes.model) nodes.model.textContent = data.model;
    } else if (kind === "text") {
      state.answer += String(event.text || "");
      paint(target, state, true);
    } else if (kind === "thinking") {
      state.thinking += String(event.text || "");
      paint(target, state, true);
    } else if (kind === "tool_start") {
      state.trace.push(`→ ${data.name || "工具"}`);
      paint(target, state, true);
    } else if (kind === "tool_end") {
      state.trace[state.trace.length - 1] = `✓ ${data.preview || "完成"}`;
      paint(target, state, true);
    } else if (kind === "done") {
      const finalText = String(data.text || "");
      if (finalText) state.answer = finalText;
      paint(target, state, false);
    } else if (kind === "error") {
      state.error = String(event.text || "未知原因");
      paint(target, state, false);
    }
  };

  try {
    await streamChat({
      message,
      conversation_id: conversationId || null,
      module: "cet6",
      surface: "cet6",
      mode: "explain",
      context_snapshot: payload,
    }, onEvent, controller.signal);
  } catch (error) {
    if (error?.name === "AbortError") {
      state.answer = (state.answer ? `${state.answer}\n\n` : "") + "（已停止）";
    } else {
      state.error = error?.message || String(error);
    }
    paint(target, state, false);
  } finally {
    abort = null;
    runId = "";
    setStreaming(false);
    pendingSelection = "";
    refreshContext();
  }
}

async function stop() {
  const controller = abort;
  if (controller) controller.abort();
  try {
    await stopChat(runId, conversationId || null);
  } catch {
    // 服务端没收到停止也没关系：连接断开后这一轮仍会跑完并落库
  }
  setStreaming(false);
}

// ---- 抽屉开关 ----

function openDock(view = "chat") {
  if (!nodes || !enabled) return;
  nodes.dock.hidden = false;
  nodes.fab.classList.add("on");
  nodes.fab.setAttribute("aria-expanded", "true");
  host.classList.add("cet6-ai-open");
  floating?.hideSelection();
  watchContext();
  showView(view);
  if (!loaded) {
    loaded = true;
    if (conversationId) loadConversation(conversationId);
    else welcome();
  } else {
    refreshContext();
  }
}

function closeDock() {
  if (!nodes) return;
  nodes.dock.hidden = true;
  nodes.fab.classList.remove("on");
  nodes.fab.setAttribute("aria-expanded", "false");
  host?.classList.remove("cet6-ai-open");
  stopWatching();
}

function toggleDock() {
  if (!nodes) return;
  if (nodes.dock.hidden) openDock("chat");
  else closeDock();
}

// ---- 绑定 ----

function bind() {
  const dock = nodes.dock;
  on(dock, "click", (event) => {
    const tab = event.target.closest("[data-ai-tab]");
    if (tab) {
      showView(tab.dataset.aiTab);
      return;
    }
    const row = event.target.closest("[data-conv]");
    if (row) {
      openConversation(Number(row.dataset.conv));
      return;
    }
    const action = event.target.closest("[data-ai]");
    if (!action) return;
    const name = action.dataset.ai;
    if (name === "send") send();
    else if (name === "stop") stop();
    else if (name === "new") newConversation();
    else if (name === "close") closeDock();
  });

  on(nodes.suggest, "click", (event) => {
    const button = event.target.closest("[data-suggest]");
    if (!button) return;
    nodes.input.value = button.dataset.suggest || "";
    nodes.input.focus();
  });

  on(nodes.input, "keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  });

  on(nodes.historySearch, "input", () => {
    historyQuery = nodes.historySearch.value || "";
    renderHistoryNow();
  });

  on(document, "keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
        && String(event.key).toLowerCase() === "j") {
      event.preventDefault();
      toggleDock();
    } else if (event.key === "Escape" && !nodes.dock.hidden) {
      closeDock();
    }
  });
}

// ---- 对外接口 ----

/** 页面注册当前上下文；返回 null 表示这一页没有具体对象。 */
export function setContextProvider(fn) {
  provider = typeof fn === "function" ? fn : null;
  refreshContext();
}

export function clearContextProvider() {
  provider = null;
  refreshContext();
}

/** 精听标签里已有 iframe 自带的 AI，外层入口在这一页隐藏。 */
export function setEnabled(next) {
  enabled = !!next;
  if (!nodes) return;
  nodes.fab.hidden = !enabled;
  if (!enabled) {
    floating?.hideSelection();
    closeDock();
  }
}

export function setPage(tab) {
  if (tab && TAB_NAMES[tab]) {
    if (tab !== activeTab) note(`切到${TAB_NAMES[tab]}页`);
    activeTab = tab;
  }
  if (nodes) renderSuggest(nodes.suggest, SUGGESTS[activeTab] || FALLBACK_SUGGESTS);
  refreshContext();
}

export function openAI(view = "chat") {
  openDock(view);
}

export function mount(root) {
  if (nodes || !root) return () => {};
  host = root;
  nodes = buildDom(host);
  bind();
  loaded = false;
  floating = installFloating({
    fab: nodes.fab,
    sel: nodes.sel,
    host,
    isEnabled: () => enabled,
    onToggle: toggleDock,
    onOpen: () => openDock("chat"),
    onSelect: (text) => {
      pendingSelection = String(text || "");
      refreshContext();
    },
  });
  return () => {
    abort?.abort();
    abort = null;
    streaming = false;
    stopWatching();
    floating?.cleanup();
    floating = null;
    for (const unbind of bindings.splice(0)) {
      try { unbind(); } catch { /* 忽略 */ }
    }
    host?.classList.remove("cet6-ai-open");
    nodes?.fab.remove();
    nodes?.sel.remove();
    nodes?.dock.remove();
    nodes = null;
    host = null;
    provider = null;
    activeView = "chat";
  };
}

// 供页面判断当前上下文是否已经注册（调试与测试用）。
export function hasContext() {
  return Boolean(safeProvider(provider));
}
