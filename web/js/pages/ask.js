// 问一问：会话列表 + 流式对话 + 附件 + Markdown/公式/代码 + 工具轨迹。
import { api, stopChat, streamChat, upload } from "../api.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, relative, toast } from "../ui.js";

const MODE_NAMES = { explain: "讲解", guide: "引导", quiz: "测验", quick: "速答" };
const TOOL_NAMES = {
  search_records: "查本地记录",
  today_summary: "看今日概览",
  read_attachment: "读文档",
  ocr_image: "OCR 看图",
};

const state = {
  mounted: false,
  conversations: [],
  convId: null,
  messages: [],
  streaming: false,
  controller: null,
  timer: 0,
  image: null,
  doc: null,
  mode: "explain",
  assistant: null,
  text: "",
  thinking: "",
  startedAt: 0,
  usedTools: new Set(),
  usedVision: false,
  stopped: false,
};

let ctxRef = null;
let dom = {};

function resetState() {
  Object.assign(state, {
    mounted: false,
    conversations: [],
    convId: null,
    messages: [],
    streaming: false,
    controller: null,
    timer: 0,
    image: null,
    doc: null,
    mode: localStorage.getItem("learnsys_mode") || "explain",
    assistant: null,
    text: "",
    thinking: "",
    startedAt: 0,
    usedTools: new Set(),
    usedVision: false,
    stopped: false,
  });
}

export async function mount(ctx) {
  resetState();
  ctxRef = ctx;
  state.mounted = true;
  state.convId = Number(ctx.params[0]) || null;

  dom = {
    thread: ctx.root.querySelector("#thread"),
    inner: ctx.root.querySelector("#thread-inner"),
    convList: ctx.root.querySelector("#conv-list"),
    input: ctx.root.querySelector("#input"),
    form: ctx.root.querySelector("#composer"),
    mode: ctx.root.querySelector("#mode"),
    send: ctx.root.querySelector("#send"),
    stop: ctx.root.querySelector("#stop"),
    status: ctx.root.querySelector("#composer-status"),
    attachRow: ctx.root.querySelector("#attach-row"),
    fileImage: ctx.root.querySelector("#file-image"),
    fileDoc: ctx.root.querySelector("#file-doc"),
  };

  dom.mode.value = MODE_NAMES[state.mode] ? state.mode : "explain";
  state.mode = dom.mode.value;
  bindEvents();
  updateSendButton();
  window.addEventListener("learnsys:answer-think", onAnswerThink);

  await loadConversations();
  if (state.convId) {
    await openConversation(state.convId, { replaceHash: false, quiet: true });
  } else {
    renderThread();
    setSubDefault();
  }
}

export function unmount() {
  state.mounted = false;
  state.controller?.abort();
  clearInterval(state.timer);
  window.removeEventListener("learnsys:answer-think", onAnswerThink);
}

function onAnswerThink() {
  if (!dom.input) return;
  dom.input.focus();
  if (!dom.input.value.trim()) {
    dom.input.value = "我的回答：";
    dom.input.dispatchEvent(new Event("input"));
  }
  dom.status.textContent = "写下你的答案，Enter 发送";
}

function setSubDefault() {
  ctxRef?.setSub("同一个 Agent：横栏、工作台共用提示词、工具和记录");
}

function bindEvents() {
  dom.form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage();
  });

  dom.input.addEventListener("input", () => {
    dom.input.style.height = "auto";
    dom.input.style.height = Math.min(dom.input.scrollHeight, 200) + "px";
    updateSendButton();
  });

  dom.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      sendMessage();
    }
  });

  dom.mode.addEventListener("change", () => {
    state.mode = dom.mode.value;
    localStorage.setItem("learnsys_mode", state.mode);
  });

  ctxRef.root.querySelector("#new-conv").addEventListener("click", newConversation);
  dom.stop.addEventListener("click", stopStreaming);

  ctxRef.root.querySelector("#attach-image").addEventListener("click", () => dom.fileImage.click());
  ctxRef.root.querySelector("#attach-doc").addEventListener("click", () => dom.fileDoc.click());

  dom.fileImage.addEventListener("change", () => pickFile(dom.fileImage, "image"));
  dom.fileDoc.addEventListener("change", () => pickFile(dom.fileDoc, "doc"));

  dom.attachRow.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-remove]");
    if (!button) return;
    if (button.dataset.remove === "image") state.image = null;
    if (button.dataset.remove === "doc") state.doc = null;
    renderAttachments();
  });
}

function updateSendButton() {
  const hasText = dom.input.value.trim().length > 0;
  dom.send.disabled = state.streaming || (!hasText && !state.image && !state.doc);
}

async function loadConversations() {
  try {
    const data = await api.get("/api/conversations?limit=30");
    state.conversations = Array.isArray(data.items) ? data.items : [];
  } catch (error) {
    toast(error.message || "会话列表没读出来", "err");
    state.conversations = [];
  }
  renderConversations();
}

function renderConversations() {
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

async function newConversation() {
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

async function openConversation(id, options = {}) {
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

function messageText(content) {
  if (typeof content === "string") return content;
  if (content && typeof content === "object") return String(content.text || "");
  return "";
}

function messageThinking(content) {
  if (content && typeof content === "object") return String(content.thinking || "");
  return "";
}

function renderThread() {
  dom.inner.innerHTML = "";
  if (!state.messages.length) {
    dom.inner.innerHTML = `<div class="empty ask-empty">
      <strong>从一句话开始</strong>
      可以挂一张截图或一份课件；回答会引用你本地的学习记录。
      <div class="ask-examples">
        <button type="button" data-example="把我今天问过的问题串一遍，找出重复出现的薄弱点">把我今天问过的问题串一遍</button>
        <button type="button" data-example="用引导模式帮我拆解一道题，先别给答案">引导我拆一道题</button>
        <button type="button" data-example="看看我挂的这份文档，先讲清楚它的整体结构">讲清这份文档的结构</button>
      </div>
    </div>`;
    dom.inner.querySelectorAll("[data-example]").forEach((button) => {
      button.addEventListener("click", () => {
        dom.input.value = button.dataset.example || "";
        dom.input.dispatchEvent(new Event("input"));
        dom.input.focus();
      });
    });
    return;
  }

  for (const message of state.messages) {
    if (message.role === "user") {
      addUserBlock(messageText(message.content));
    } else if (message.role === "assistant") {
      const text = messageText(message.content);
      const thinking = messageThinking(message.content);
      if (text) {
        const block = createAssistantBlock();
        renderInto(block.body, text);
        block.body.hidden = false;
        if (thinking) {
          block.thinkingEl.hidden = false;
          block.thinkingPre.textContent = thinking;
        }
        dom.inner.appendChild(block.wrap);
      } else if (message.content?.error) {
        const block = createAssistantBlock();
        block.error.hidden = false;
        block.error.textContent = message.content.error;
      } else {
        const block = createAssistantBlock();
        block.wrap.remove();
      }
    }
  }
}

function addUserBlock(text) {
  const node = document.createElement("div");
  node.className = "msg-user";
  node.textContent = text;
  dom.inner.appendChild(node);
  return node;
}

function createAssistantBlock() {
  const wrap = document.createElement("div");
  wrap.className = "msg-assistant";

  const status = document.createElement("div");
  status.className = "assistant-status";
  status.hidden = true;

  const thinkingEl = document.createElement("details");
  thinkingEl.className = "thinking";
  thinkingEl.hidden = true;
  const thinkingSummary = document.createElement("summary");
  thinkingSummary.textContent = "思考过程";
  const thinkingPre = document.createElement("pre");
  thinkingEl.append(thinkingSummary, thinkingPre);

  const toolsEl = document.createElement("details");
  toolsEl.className = "tools";
  toolsEl.hidden = true;
  const toolsSummary = document.createElement("summary");
  toolsSummary.textContent = "工具轨迹";
  const toolsBody = document.createElement("div");
  toolsEl.append(toolsSummary, toolsBody);

  const body = document.createElement("div");
  body.className = "md";
  body.hidden = true;

  const error = document.createElement("div");
  error.className = "error-bar";
  error.hidden = true;

  const sources = document.createElement("div");
  sources.className = "sources";

  wrap.append(status, thinkingEl, toolsEl, body, error, sources);
  dom.inner.appendChild(wrap);
  return {
    wrap, status, thinkingEl, thinkingPre, toolsEl, toolsSummary, toolsBody,
    body, error, sources,
  };
}

function setAssistantStatus(block, text, spinning = false) {
  block.status.hidden = false;
  block.status.innerHTML = `${spinning ? '<span class="pulse"></span>' : ""}<span>${escapeHtml(text)}</span>`;
}

function paintAssistant(force = false) {
  const block = state.assistant;
  if (!block) return;
  const stick = nearBottom();
  renderInto(block.body, state.text);
  block.body.hidden = !state.text;
  if (force || stick) scrollBottom();
}

function nearBottom() {
  return dom.thread.scrollHeight - dom.thread.scrollTop - dom.thread.clientHeight < 140;
}

function scrollBottom(force = false) {
  if (force) dom.thread.scrollTop = dom.thread.scrollHeight;
  else if (nearBottom()) dom.thread.scrollTop = dom.thread.scrollHeight;
}

function addToolRow(block, name, input) {
  if (block.toolsEl.hidden) block.toolsEl.hidden = false;
  const row = document.createElement("div");
  row.className = "tool-row";
  row.dataset.name = name;
  row.innerHTML = `<span class="tool-name">${escapeHtml(TOOL_NAMES[name] || name)}</span>
    <span class="tool-preview">${escapeHtml(toolInputPreview(input))}</span>`;
  block.toolsBody.appendChild(row);
  const count = block.toolsBody.children.length;
  block.toolsSummary.textContent = `工具轨迹 · ${count} 次`;
  state.usedTools.add(name);
}

function toolInputPreview(input) {
  if (!input || typeof input !== "object") return "";
  if (input.query) return String(input.query);
  if (input.offset) return `从第 ${input.offset} 字`;
  return "";
}

function updateToolPreview(block, name, preview) {
  const rows = [...block.toolsBody.querySelectorAll(".tool-row")];
  const row = rows.reverse().find((item) => item.dataset.name === name);
  if (!row) return;
  const slot = row.querySelector(".tool-preview");
  if (slot) slot.textContent = String(preview || "").slice(0, 90);
}

function addSource(block, label) {
  const chip = document.createElement("span");
  chip.className = "source-chip";
  chip.textContent = label;
  block.sources.appendChild(chip);
}

async function pickFile(input, kind) {
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (state.streaming) {
    toast("先等这一轮写完再挂附件");
    return;
  }
  dom.status.textContent = kind === "image" ? "正在读取图片…" : "正在读文档…";
  try {
    const result = await upload(file);
    if (!state.mounted) return;
    if (result.kind === "image") {
      state.image = { path: result.path, name: result.name || file.name };
      dom.status.textContent = "图片已挂上";
    } else {
      state.doc = {
        name: result.name || file.name,
        text: result.text || "",
        chars: result.chars || 0,
        truncated: !!result.truncated,
      };
      dom.status.textContent = result.truncated ? "文档太长，只取前 20 万字" : "文档已挂上";
    }
    renderAttachments();
    updateSendButton();
  } catch (error) {
    dom.status.textContent = "";
    toast(error.message || "附件没读出来", "err");
  }
}

function renderAttachments() {
  const items = [];
  if (state.image) {
    items.push(`<span class="attach-chip">图片 · ${escapeHtml(state.image.name)}
      <button type="button" data-remove="image" aria-label="移除图片">×</button></span>`);
  }
  if (state.doc) {
    items.push(`<span class="attach-chip">文档 · ${escapeHtml(state.doc.name)} · ${state.doc.chars} 字
      <button type="button" data-remove="doc" aria-label="移除文档">×</button></span>`);
  }
  dom.attachRow.innerHTML = items.join("");
  dom.attachRow.hidden = items.length === 0;
}

function sendMessage() {
  if (state.streaming) return;
  const text = dom.input.value.trim();
  if (!text && !state.image && !state.doc) return;

  const message = text || (state.image ? "看看这张图" : "看看这份文档");
  const payload = {
    message,
    conversation_id: state.convId,
    mode: state.mode,
    image_path: state.image?.path || null,
    attachment_name: state.doc?.name || "",
    attachment_text: state.doc?.text || "",
  };

  if (state.messages.length === 0) dom.inner.innerHTML = "";
  const shown = message
    + (state.image ? `\n［图片：${state.image.name}］` : "")
    + (state.doc ? `\n［文档：${state.doc.name}］` : "");
  addUserBlock(shown);
  state.messages.push({ role: "user", content: { text: message } });

  dom.input.value = "";
  dom.input.style.height = "auto";
  state.image = null;
  state.doc = null;
  renderAttachments();
  dom.status.textContent = "";
  scrollBottom(true);

  startStreaming(payload);
}

async function startStreaming(payload) {
  state.streaming = true;
  state.stopped = false;
  state.text = "";
  state.thinking = "";
  state.usedTools = new Set();
  state.usedVision = false;
  state.startedAt = Date.now();
  state.assistant = createAssistantBlock();
  setAssistantStatus(state.assistant, "思考中", true);
  dom.input.disabled = true;
  dom.send.hidden = true;
  dom.stop.hidden = false;
  dom.mode.disabled = true;
  updateSendButton();

  state.timer = setInterval(() => {
    if (!state.assistant) return;
    const seconds = Math.max(1, Math.round((Date.now() - state.startedAt) / 1000));
    const label = state.text ? "正在写" : "思考中";
    setAssistantStatus(state.assistant, `${label} · ${seconds} 秒`, true);
  }, 1000);

  state.controller = new AbortController();
  let paintTimer = 0;
  const schedulePaint = () => {
    if (paintTimer) return;
    paintTimer = setTimeout(() => {
      paintTimer = 0;
      paintAssistant();
    }, 110);
  };

  try {
    await streamChat(payload, (event) => {
      const block = state.assistant;
      if (!block) return;
      if (event.kind === "start") {
        const id = Number(event.data?.conversation_id || 0);
        if (id && state.convId !== id) {
          state.convId = id;
          history.replaceState(null, "", `#/ask/${id}`);
        }
      } else if (event.kind === "thinking") {
        state.thinking += event.text || "";
        block.thinkingEl.hidden = false;
        block.thinkingPre.textContent = state.thinking;
        setAssistantStatus(block, "思考中", true);
      } else if (event.kind === "text") {
        state.text += event.text || "";
        setAssistantStatus(block, state.text ? "正在写" : "思考中", true);
        schedulePaint();
      } else if (event.kind === "tool_start") {
        addToolRow(block, event.data?.name || "tool", event.data?.input || {});
        setAssistantStatus(block, "在查本地记录", true);
      } else if (event.kind === "tool_end") {
        updateToolPreview(block, event.data?.name || "", event.data?.preview || "");
      } else if (event.kind === "vision") {
        if (typeof event.data?.used_vision === "boolean") {
          state.usedVision = event.data.used_vision;
        } else {
          setAssistantStatus(block, "正在看图", true);
        }
      } else if (event.kind === "done") {
        const finalText = String(event.data?.text || state.text || "");
        if (finalText) state.text = finalText;
        if (event.data?.thinking) state.thinking = String(event.data.thinking);
        paintAssistant(true);
        finishStreaming(block, true);
      } else if (event.kind === "error") {
        showStreamError(block, event.text || "模型没有回答");
      }
    }, state.controller.signal);
    if (state.streaming) finishStreaming(state.assistant, true);
  } catch (error) {
    if (error?.name === "AbortError") {
      finishStreaming(state.assistant, false, "已停止，答案保留到中断处");
    } else {
      showStreamError(state.assistant, error?.message || "连接中断了");
    }
  } finally {
    clearTimeout(paintTimer);
  }
}

function finishStreaming(block, ok, note = "") {
  if (!state.streaming) return;
  state.streaming = false;
  clearInterval(state.timer);
  state.timer = 0;
  dom.input.disabled = false;
  dom.send.hidden = false;
  dom.stop.hidden = true;
  dom.mode.disabled = false;
  updateSendButton();

  if (!block) return;
  const seconds = Math.max(1, Math.round((Date.now() - state.startedAt) / 1000));

  if (ok) {
    if (state.text) paintAssistant(true);
    setAssistantStatus(block, `用了 ${seconds} 秒`);
    for (const name of state.usedTools) addSource(block, TOOL_NAMES[name] || name);
    if (state.usedVision) addSource(block, "视觉模型");
    if (state.text) {
      state.messages.push({ role: "assistant", content: { text: state.text, thinking: state.thinking } });
    }
  } else {
    setAssistantStatus(block, note || "已停止");
    if (state.text) {
      paintAssistant(true);
      state.messages.push({ role: "assistant", content: { text: state.text, thinking: state.thinking } });
    }
  }

  if (state.convId) loadConversations();
  dom.input.focus();
}

function showStreamError(block, message) {
  state.streaming = false;
  clearInterval(state.timer);
  state.timer = 0;
  dom.input.disabled = false;
  dom.send.hidden = false;
  dom.stop.hidden = true;
  dom.mode.disabled = false;
  updateSendButton();
  if (block) {
    block.error.hidden = false;
    block.error.textContent = String(message || "出错了");
    setAssistantStatus(block, "出错了");
    if (state.text) paintAssistant(true);
  }
  if (state.convId) loadConversations();
}

async function stopStreaming() {
  if (!state.streaming) return;
  state.stopped = true;
  dom.status.textContent = "正在停止…";
  state.controller?.abort();
  try {
    await stopChat(state.convId);
  } catch {
    // 已经断了就不用再报
  }
  dom.status.textContent = "";
}
