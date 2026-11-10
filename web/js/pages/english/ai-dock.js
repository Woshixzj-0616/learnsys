// AI 抽屉外壳：圆圈与划词安装、抽屉开关、上下文行、建议问题、视图切换与事件绑定。
// 会话数据与 SSE 在 ai-session.js；这里只做 DOM 与交互，并把宿主接口注入会话层。
import { TAB_NAMES, contextLine, safeProvider } from "./ai-context.js";
import { installFloating } from "./ai-floating.js";
import {
  FALLBACK_SUGGESTS, SUGGESTS, buildDom, paintBubble, renderSuggest, renderWelcome,
} from "./ai-view.js";
import {
  attachDock, currentConversation, isLoaded, loadConversation, loadHistory,
  markLoaded, newConversation, note, openConversation, reset as resetSession,
  send, setHistoryQuery, stop,
} from "./ai-session.js";

let host = null;
let nodes = null;
let floating = null;
let enabled = true;
let activeTab = "listening";
let provider = null;
let pendingSelection = "";
let activeView = "chat";
let observer = null;
let contextPending = false;
const bindings = [];

function on(target, type, fn, options) {
  target.addEventListener(type, fn, options);
  bindings.push(() => target.removeEventListener(type, fn, options));
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

function clearSelection() {
  pendingSelection = "";
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
  if (!nodes) return;
  nodes.send.hidden = !!next;
  nodes.stop.hidden = !next;
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
  if (!isLoaded()) {
    markLoaded(true);
    if (currentConversation()) loadConversation(currentConversation());
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
    setHistoryQuery(nodes.historySearch.value || "");
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
  attachDock({
    nodes: () => nodes,
    context: () => ({ activeTab, selection: pendingSelection, provider }),
    showView, welcome, paint, setStreaming, refreshContext, scrollBottom,
    clearSelection,
  });
  bind();
  markLoaded(false);
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
    resetSession();
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
