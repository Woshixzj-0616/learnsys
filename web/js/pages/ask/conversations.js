// 会话列表：读取、切换、新建。
import { api } from "../../api.js";
import { escapeHtml, relative, toast } from "../../ui.js";
import { MODE_NAMES, ctxRef, state, dom, setSubDefault } from "./state.js";
import { renderThread } from "./thread.js";
import { renderAttachments, updateSendButton } from "./attachments.js";


export async function loadConversations() {
  try {
    const data = await api.get("/api/conversations?limit=30");
    state.conversations = Array.isArray(data.items) ? data.items : [];
  } catch (error) {
    toast(error.message || "会话列表没读出来", "err");
    state.conversations = [];
  }
  renderConversations();
}

export function renderConversations() {
  if (!dom.convList) return;
  if (!state.conversations.length) {
    dom.convList.innerHTML = '<div class="hint" style="padding:8px 10px">还没有会话</div>';
    return;
  }
  dom.convList.innerHTML = state.conversations.map((item) => `
    <button class="conv-item${item.id === state.convId ? " active" : ""}"
        type="button" data-id="${item.id}">
      <div class="conv-title">${escapeHtml(item.title || "新对话")}</div>
      <div class="conv-meta">${escapeHtml(relative(item.updated_at))} · ${item.messages} 条</div>
    </button>`).join("");
  dom.convList.querySelectorAll("[data-id]").forEach((node) => {
    node.addEventListener("click", () => openConversation(Number(node.dataset.id)));
  });
}

export async function newConversation() {
  if (state.streaming) {
    toast("先停止正在写的回答，再开新对话");
    return;
  }
  state.convId = null;
  state.messages = [];
  state.assistant = null;
  state.image = null;
  state.doc = null;
  renderAttachments();
  dom.input.value = "";
  dom.input.style.height = "auto";
  dom.status.textContent = "";
  dom.inner.innerHTML = "";
  renderThread();
  renderConversations();
  setSubDefault();
  history.replaceState(null, "", "#/ask");
  dom.input.focus();
  updateSendButton();
}

export async function openConversation(id, options = {}) {
  if (!id || state.streaming) {
    if (state.streaming) toast("先停止正在写的回答，再换会话");
    return;
  }
  try {
    const data = await api.get(`/api/conversations/${id}`);
    if (!state.mounted) return;
    state.convId = data.id;
    state.assistant = null;
    state.messages = Array.isArray(data.messages) ? data.messages : [];
    if (!options.quiet) {
      history.replaceState(null, "", `#/ask/${data.id}`);
      ctxRef?.setSub(`${data.title || "对话"} · ${MODE_NAMES[data.mode] || "讲解"}模式`);
    }
    renderThread();
    renderConversations();
    scrollBottom(true);
    updateSendButton();
  } catch (error) {
    toast(error.message || "会话没打开", "err");
  }
}
