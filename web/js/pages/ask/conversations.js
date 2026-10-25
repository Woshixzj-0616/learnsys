// 会话列表：读取、切换、新建。
import { api } from "../../api.js";
import { escapeHtml, relative, toast } from "../../ui.js";
import { MODE_NAMES, ctxRef, state, dom, setSubDefault } from "./state.js";
import { renderThread, scrollBottom } from "./thread.js";
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
  dom.convList.innerHTML = state.conversations.map((item) => {
    const badge = item.origin === "video"
      ? '<span class="conv-origin">录像</span>' : "";
    const from = item.origin === "video" && item.recording_title
      ? ` · ${escapeHtml(item.recording_title)}` : "";
    return `<button class="conv-item${item.id === state.convId ? " active" : ""}"
        type="button" data-id="${item.id}">
      <div class="conv-title">${badge}${escapeHtml(item.title || "新对话")}</div>
      <div class="conv-meta">${escapeHtml(relative(item.updated_at))} · ${item.messages} 条${from}</div>
    </button>`;
  }).join("");
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
  state.recording = null;
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
    if (data.origin === "video" && data.recording_id) {
      try {
        const rec = await api.get(`/api/recordings/${data.recording_id}`);
        state.recording = { id: rec.id, title: rec.title, chars: rec.chars };
      } catch (error) {
        state.recording = {
          id: data.recording_id, title: data.recording_title || "录像", chars: 0,
        };
      }
    } else {
      state.recording = null;
    }
    renderAttachments();
    if (!options.quiet) {
      history.replaceState(null, "", `#/ask/${data.id}`);
      const source = data.origin === "video"
        ? `录像 · ${data.recording_title || "这段录像"} · ` : "";
      ctxRef?.setSub(`${source}${data.title || "对话"} · ${MODE_NAMES[data.mode] || "讲解"}模式`);
    }
    renderThread();
    renderConversations();
    scrollBottom(true);
    updateSendButton();
  } catch (error) {
    toast(error.message || "会话没打开", "err");
  }
}
