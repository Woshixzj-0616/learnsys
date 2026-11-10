// AI 抽屉的会话层：对话读取、SSE 流式发送、停止与历史列表。
// 只碰数据与请求；DOM 渲染和抽屉开关由 ai-dock.js 通过 attachDock 注入。
import { api, streamChat, stopChat } from "../../api.js";
import { escapeHtml } from "../../ui.js";
import { TAB_NAMES, snapshotOf } from "./ai-context.js";
import { addMessage, renderHistory, status } from "./ai-view.js";

const CONV_KEY = "learnsys_cet6_ai_conv";

// 由 ai-dock.js 注入的宿主接口，避免会话层反向依赖抽屉层。
let dock = null;
let conversationId = readNumber(CONV_KEY);
let streaming = false;
let abort = null;
let runId = "";
let loaded = false;
let historyRows = [];
let historyQuery = "";
let historyLoading = false;
let recentActions = [];

function readNumber(key) {
  try { return Number(localStorage.getItem(key)) || 0; } catch { return 0; }
}

function saveNumber(key, value) {
  try { localStorage.setItem(key, String(Number(value) || 0)); } catch { /* 忽略 */ }
}

function shorten(text, limit = 24) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

/** 抽屉层注册宿主接口；所有渲染动作都从这里回调。 */
export function attachDock(api) {
  dock = api;
}

export function currentConversation() {
  return conversationId;
}

export function isLoaded() {
  return loaded;
}

export function markLoaded(next = true) {
  loaded = !!next;
}

export function isStreaming() {
  return streaming;
}

/** 卸载时收尾：断开流、清掉本轮的停止句柄。 */
export function reset() {
  abort?.abort();
  abort = null;
  streaming = false;
  runId = "";
}

function setConversation(id) {
  conversationId = Number(id) || 0;
  saveNumber(CONV_KEY, conversationId);
}

export function note(text) {
  const value = String(text || "").trim();
  if (!value) return;
  recentActions.push(value);
  if (recentActions.length > 20) recentActions = recentActions.slice(-20);
}

function storedText(content) {
  if (content == null) return "";
  if (typeof content === "string") return content;
  return String(content.text || "");
}

function renderStored(message) {
  const nodes = dock?.nodes();
  if (!nodes) return;
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
  dock.paint(target, { answer: text, thinking, trace: [], error: "" }, false);
}

export async function loadConversation(id) {
  const nodes = dock?.nodes();
  if (!nodes) return;
  id = Number(id) || 0;
  if (!id) {
    dock.welcome();
    return;
  }
  nodes.messages.innerHTML = status("正在读取对话…");
  try {
    const data = await api.get(`/api/conversations/${id}`);
    nodes.messages.innerHTML = "";
    (data.messages || []).forEach(renderStored);
    if (!(data.messages || []).length) dock.welcome();
    setConversation(data.id || id);
    dock.refreshContext();
    dock.scrollBottom();
  } catch (error) {
    nodes.messages.innerHTML = "";
    addMessage(nodes.messages, "error", `读取对话失败：${error.message || error}`);
  }
}

export function renderHistoryNow() {
  const nodes = dock?.nodes();
  if (!nodes?.historyList) return;
  renderHistory(nodes.historyList, historyRows, historyQuery, conversationId);
}

export function setHistoryQuery(text) {
  historyQuery = String(text || "");
  renderHistoryNow();
}

export async function loadHistory() {
  const nodes = dock?.nodes();
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

export async function openConversation(id) {
  if (streaming) await stop();
  dock?.showView("chat");
  await loadConversation(id);
}

export function newConversation() {
  const nodes = dock?.nodes();
  if (streaming) stop();
  setConversation(0);
  loaded = true;
  dock?.clearSelection();
  if (nodes) nodes.messages.innerHTML = "";
  dock?.welcome();
  dock?.showView("chat");
  nodes?.input.focus();
}

export async function send() {
  const nodes = dock?.nodes();
  if (streaming || !nodes) return;
  const message = String(nodes.input.value || "").trim();
  if (!message) return;
  nodes.input.value = "";
  addMessage(nodes.messages, "user", message);
  const target = addMessage(nodes.messages, "assistant", "");
  const state = { answer: "", thinking: "", trace: [], error: "" };
  dock.paint(target, state, true);

  note(`提问：${shorten(message, 60)}`);
  let payload;
  try {
    payload = snapshotOf({
      ...dock.context(), tabNames: TAB_NAMES, recentActions,
    });
  } catch (error) {
    state.error = error.message || "上下文没组装好";
    dock.paint(target, state, false);
    return;
  }

  const controller = new AbortController();
  abort = controller;
  runId = "";
  streaming = true;
  dock.setStreaming(true);

  const onEvent = (event) => {
    const kind = event.kind;
    const data = event.data || {};
    if (kind === "start") {
      if (data.conversation_id) setConversation(data.conversation_id);
      if (data.run_id) runId = String(data.run_id);
      if (data.model && nodes.model) nodes.model.textContent = data.model;
    } else if (kind === "text") {
      state.answer += String(event.text || "");
      dock.paint(target, state, true);
    } else if (kind === "thinking") {
      state.thinking += String(event.text || "");
      dock.paint(target, state, true);
    } else if (kind === "tool_start") {
      state.trace.push(`→ ${data.name || "工具"}`);
      dock.paint(target, state, true);
    } else if (kind === "tool_end") {
      state.trace[state.trace.length - 1] = `✓ ${data.preview || "完成"}`;
      dock.paint(target, state, true);
    } else if (kind === "done") {
      const finalText = String(data.text || "");
      if (finalText) state.answer = finalText;
      dock.paint(target, state, false);
    } else if (kind === "error") {
      state.error = String(event.text || "未知原因");
      dock.paint(target, state, false);
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
    dock.paint(target, state, false);
  } finally {
    abort = null;
    runId = "";
    streaming = false;
    dock.setStreaming(false);
    dock.clearSelection();
    dock.refreshContext();
  }
}

export async function stop() {
  const controller = abort;
  if (controller) controller.abort();
  try {
    await stopChat(runId, conversationId || null);
  } catch {
    // 服务端没收到停止也没关系：连接断开后这一轮仍会跑完并落库
  }
  streaming = false;
  dock?.setStreaming(false);
}
