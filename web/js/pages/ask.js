// 问一问：会话列表 + 流式对话 + 附件 + Markdown/公式/代码 + 工具轨迹。
import { api, stopChat, streamChat, upload } from "../api.js";
import { buildSnapshot } from "../context.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, relative, toast } from "../ui.js";

const MODE_NAMES = { explain: "讲解", guide: "引导", quiz: "测验", quick: "速答" };
const TOOL_NAMES = {
  search_records: "查本地记录",
  today_summary: "看今日概览",
  recent_wrong_items: "查错题本",
  read_attachment: "读文档",
  ocr_image: "OCR 看图",
  search_materials: "搜资料库",
  read_material: "读资料",
  get_cet6_context: "读六级进度",
  save_wrongbook: "收错题",
  save_memory: "记长期偏好",
  forget_memory: "忘掉记忆",
  save_material_note: "存资料笔记",
  write_study_file: "写学习档案",
  run_code: "运行代码",
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
  material: null,
  mode: "explain",
  assistant: null,
  text: "",
  thinking: "",
  startedAt: 0,
  runId: "",
  usedTools: new Set(),
  usedVision: false,
  stopped: false,
  thinkingDirty: false,
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
    material: null,
    mode: localStorage.getItem("learnsys_mode") || "explain",
    assistant: null,
    text: "",
    thinking: "",
    startedAt: 0,
    runId: "",
    usedTools: new Set(),
    usedVision: false,
    stopped: false,
    thinkingDirty: false,
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
    materialPicker: ctx.root.querySelector("#material-picker"),
    materialList: ctx.root.querySelector("#material-list"),
    materialSearch: ctx.root.querySelector("#material-search"),
    materialClose: ctx.root.querySelector("#material-close"),
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

  // 插件联动：`#/ask?material=12` 从资料库挂载；`prompt=` 预填问题，不自动发送
  const materialId = Number(ctx.query?.get("material") || 0);
  if (materialId) {
    try {
      const data = await api.get(`/api/materials/${materialId}?body=0`);
      state.material = { id: data.item.id, title: data.item.title, chars: data.item.chars };
      renderAttachments();
      updateSendButton();
      dom.status.textContent = `已挂资料：${data.item.title}`;
    } catch (error) {
      toast(error.message || "资料没挂上", "err");
    }
  }
  const prompt = ctx.query?.get("prompt");
  if (prompt) {
    dom.input.value = prompt;
    dom.input.dispatchEvent(new Event("input"));
    dom.input.focus();
    dom.status.textContent = "题目已填好 —— 想改就直接改，按 Enter 发送";
  }
}

export function unmount() {
  state.mounted = false;
  state.controller?.abort();
  clearInterval(state.timer);
  clearTimeout(state.pickerTimer);
  window.removeEventListener("learnsys:answer-think", onAnswerThink);
  window.removeEventListener("keydown", onPickerKey);
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
  ctxRef.root.querySelector("#attach-material").addEventListener("click", openMaterialPicker);

  dom.fileImage.addEventListener("change", () => pickFile(dom.fileImage, "image"));
  dom.fileDoc.addEventListener("change", () => pickFile(dom.fileDoc, "doc"));

  dom.attachRow.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-remove]");
    if (!button) return;
    if (button.dataset.remove === "image") state.image = null;
    if (button.dataset.remove === "doc") state.doc = null;
    if (button.dataset.remove === "material") state.material = null;
    renderAttachments();
  });

  dom.materialClose.addEventListener("click", closeMaterialPicker);
  dom.materialPicker.addEventListener("click", (event) => {
    if (event.target === dom.materialPicker) closeMaterialPicker();
  });
  dom.materialSearch.addEventListener("input", () => {
    clearTimeout(state.pickerTimer);
    state.pickerTimer = setTimeout(() => loadMaterialPicker(dom.materialSearch.value), 220);
  });
  window.addEventListener("keydown", onPickerKey);
  dom.materialList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-material]");
    if (!button) return;
    state.material = {
      id: Number(button.dataset.material),
      title: button.dataset.title || "",
      chars: Number(button.dataset.chars || 0),
    };
    state.doc = null;              // 资料库和一次性文档二选一，避免两段正文互相干扰
    closeMaterialPicker();
    renderAttachments();
    updateSendButton();
    dom.status.textContent = `已挂资料：${state.material.title}`;
  });
}

function onPickerKey(event) {
  if (event.key === "Escape" && !dom.materialPicker.hidden) closeMaterialPicker();
}

async function openMaterialPicker() {
  if (state.streaming) {
    toast("先等这一轮写完再挂资料");
    return;
  }
  dom.materialPicker.hidden = false;
  dom.materialSearch.value = "";
  await loadMaterialPicker("");
  dom.materialSearch.focus();
}

function closeMaterialPicker() {
  dom.materialPicker.hidden = true;
}

async function loadMaterialPicker(query) {
  dom.materialList.innerHTML = '<div class="empty">正在读资料库…</div>';
  try {
    const params = new URLSearchParams({ status: "active", limit: "50" });
    if (query.trim()) params.set("q", query.trim());
    const data = await api.get(`/api/materials?${params}`);
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      dom.materialList.innerHTML = `<div class="empty"><strong>资料库还是空的</strong>
        去 <a href="#/materials">资料</a> 导入课件，或换个关键词。</div>`;
      return;
    }
    dom.materialList.innerHTML = items.map((item) => `
      <button class="material-pick" type="button"
        data-material="${item.id}" data-title="${escapeHtml(item.title)}"
        data-chars="${item.chars || 0}">
        <span class="material-pick-icon">${escapeHtml(item.kind || "·")}</span>
        <span class="material-pick-main">
          <strong>${escapeHtml(item.title)}</strong>
          <small>${escapeHtml(item.kind)} · ${escapeHtml(item.chars || 0)} 字${item.page ? ` · 第 ${item.page} 页` : ""}</small>
          ${item.snippet ? `<em>${escapeHtml(item.snippet)}</em>` : ""}
        </span>
      </button>`).join("");
  } catch (error) {
    dom.materialList.innerHTML = `<div class="empty">${escapeHtml(error.message || error)}</div>`;
  }
}

function updateSendButton() {
  const hasText = dom.input.value.trim().length > 0;
  dom.send.disabled = state.streaming
    || (!hasText && !state.image && !state.doc && !state.material);
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
        if (message.content?.run_id) attachReplay(block, message.content.run_id);
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

  const planEl = document.createElement("div");
  planEl.className = "plan-card";
  planEl.hidden = true;

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

  const checkEl = document.createElement("div");
  checkEl.className = "check-strip";
  checkEl.hidden = true;

  const error = document.createElement("div");
  error.className = "error-bar";
  error.hidden = true;

  const sources = document.createElement("div");
  sources.className = "sources";

  wrap.append(status, planEl, thinkingEl, toolsEl, body, checkEl, error, sources);
  dom.inner.appendChild(wrap);
  return {
    wrap, status, planEl, thinkingEl, thinkingPre, toolsEl, toolsSummary, toolsBody,
    body, checkEl, error, sources,
  };
}

const PLAN_MARKS = { pending: "○", doing: "▸", done: "✓", failed: "✗", skipped: "–" };

function renderPlan(block, steps, truncated = false) {
  if (!block || !Array.isArray(steps) || !steps.length) return;
  block.planEl.hidden = false;
  block.planEl.innerHTML = `<div class="plan-head">计划${truncated ? "（超过 6 步已截断）" : ""}</div>`
    + steps.map((step) => `
      <div class="plan-step ${escapeHtml(step.status || "pending")}">
        <span class="plan-mark">${PLAN_MARKS[step.status] || "○"}</span>
        <span class="plan-title">${escapeHtml(step.title || "")}</span>
        ${step.tool ? `<span class="plan-tool">${escapeHtml(TOOL_NAMES[step.tool] || step.tool)}</span>` : ""}
      </div>`).join("");
}

function showCheck(block, data) {
  if (!block) return;
  const issues = Array.isArray(data?.issues) ? data.issues : [];
  block.checkEl.hidden = false;
  block.checkEl.classList.toggle("bad", !data?.ok);
  if (data?.ok) {
    block.checkEl.textContent = data.rewritten
      ? "自检通过：已按工具证据重写"
      : `自检通过 · 已核对 ${Number(data.checked || 0)} 条工具结果`;
  } else {
    block.checkEl.textContent = "自检未通过：" + (issues.join("；") || "引用无法核对");
  }
}

function renderRunTrace(trace) {
  if (!Array.isArray(trace) || !trace.length) {
    return '<div class="hint">这次运行没有可回放的事件</div>';
  }
  const lines = [];
  for (const item of trace) {
    const data = item.data || {};
    if (item.kind === "plan") {
      lines.push(`<div class="run-line"><b>计划</b> ${(data.steps || []).map(
        (step, index) => `${index + 1}. ${escapeHtml(step.title || "")}`).join("；")}</div>`);
    } else if (item.kind === "tool_start") {
      lines.push(`<div class="run-line"><b>调用</b> ${escapeHtml(TOOL_NAMES[data.name] || data.name || "")}`
        + `${data.goal ? ` · 目标：${escapeHtml(data.goal)}` : ""}</div>`);
    } else if (item.kind === "tool_end") {
      lines.push(`<div class="run-line ${data.ok === false ? "bad" : ""}"><b>${data.ok === false ? "失败" : "结果"}</b> `
        + `${escapeHtml(data.preview || "")}${data.denied ? "（用户拒绝）" : ""}</div>`
        + (data.output ? `<pre class="run-output">${escapeHtml(data.output.slice(0, 4000))}</pre>` : ""));
    } else if (item.kind === "confirm") {
      lines.push(`<div class="run-line"><b>确认</b> ${escapeHtml(data.summary || "")}</div>`);
    } else if (item.kind === "check") {
      const issues = Array.isArray(data.issues) ? data.issues : [];
      lines.push(`<div class="run-line ${data.ok ? "" : "bad"}"><b>自检</b> `
        + `${data.ok ? "通过" : escapeHtml(issues.join("；"))}</div>`);
    } else if (item.kind === "rewrite") {
      lines.push('<div class="run-line"><b>重写</b> 按自检结果替换了正文</div>');
    } else if (item.kind === "error") {
      lines.push(`<div class="run-line bad"><b>错误</b> ${escapeHtml(item.text || "")}</div>`);
    }
  }
  return lines.join("") || '<div class="hint">这次运行没有可展示的步骤</div>';
}

function attachReplay(block, runId) {
  if (!block || !runId) return;
  const details = document.createElement("details");
  details.className = "run-replay";
  const summary = document.createElement("summary");
  summary.textContent = "运行回放";
  const body = document.createElement("div");
  body.className = "run-body";
  details.append(summary, body);
  details.addEventListener("toggle", async () => {
    if (!details.open || details.dataset.loaded) return;
    details.dataset.loaded = "1";
    body.innerHTML = '<div class="hint">正在读运行记录…</div>';
    try {
      const run = await api.get(`/api/agent/runs/${encodeURIComponent(runId)}`);
      body.innerHTML = renderRunTrace(run.trace);
    } catch (error) {
      body.innerHTML = `<div class="hint">${escapeHtml(error.message || "运行记录没读到")}</div>`;
    }
  });
  block.wrap.insertBefore(details, block.sources);
}

function setAssistantStatus(block, text, spinning = false) {
  block.status.hidden = false;
  block.status.innerHTML = `${spinning ? '<span class="pulse"></span>' : ""}<span>${escapeHtml(text)}</span>`;
}

function paintAssistant(force = false) {
  const block = state.assistant;
  if (!block) return;
  const stick = nearBottom();
  if (state.thinkingDirty) {
    block.thinkingPre.textContent = state.thinking;
    block.thinkingEl.querySelector("summary").textContent =
      state.text ? `思考过程 · ${state.thinking.length} 字` : `思考过程 · ${state.thinking.length} 字`;
    state.thinkingDirty = false;
  }
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

function addToolRow(block, name, input, goal = "", step = null) {
  if (block.toolsEl.hidden) block.toolsEl.hidden = false;
  const row = document.createElement("div");
  row.className = "tool-row";
  row.dataset.name = name;
  if (step !== null && step !== undefined) row.dataset.step = String(step);
  const label = goal ? `${goal} · ${TOOL_NAMES[name] || name}` : (TOOL_NAMES[name] || name);
  row.innerHTML = `<span class="tool-name">${escapeHtml(label)}</span>
    <span class="tool-preview">${escapeHtml(toolInputPreview(input))}</span>`;
  block.toolsBody.appendChild(row);
  const count = block.toolsBody.children.length;
  block.toolsSummary.textContent = `工具轨迹 · ${count} 次`;
  state.usedTools.add(name);
}

function toolInputPreview(input) {
  if (!input || typeof input !== "object") return "";
  if (input.query) return String(input.query);
  if (input.material_id) return `资料 #${input.material_id}`;
  if (input.offset) return `从第 ${input.offset} 字`;
  if (input.content) return String(input.content).slice(0, 60);
  return "";
}

function updateToolPreview(block, name, preview, ok = true, step = null) {
  let row = null;
  if (step !== null && step !== undefined) {
    const matches = [...block.toolsBody.querySelectorAll(".tool-row")]
      .filter((item) => item.dataset.step === String(step));
    row = matches[matches.length - 1] || null;
  }
  if (!row) {
    const rows = [...block.toolsBody.querySelectorAll(".tool-row")];
    row = rows.reverse().find((item) => item.dataset.name === name
      && !item.classList.contains("done") && !item.classList.contains("bad"));
  }
  if (!row) return;
  row.classList.add(ok ? "done" : "bad");
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
      state.material = null;       // 一次性文档和资料库二选一
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
  if (state.material) {
    items.push(`<span class="attach-chip">资料 · ${escapeHtml(state.material.title)} · ${state.material.chars} 字
      <button type="button" data-remove="material" aria-label="移除资料">×</button></span>`);
  }
  dom.attachRow.innerHTML = items.join("");
  dom.attachRow.hidden = items.length === 0;
}

function sendMessage() {
  if (state.streaming) return;
  const text = dom.input.value.trim();
  if (!text && !state.image && !state.doc && !state.material) return;

  const message = text || (state.image ? "看看这张图"
    : (state.material ? "看看这份资料" : "看看这份文档"));
  const payload = {
    message,
    conversation_id: state.convId,
    mode: state.mode,
    image_path: state.image?.path || null,
    attachment_name: state.material ? "" : (state.doc?.name || ""),
    attachment_text: state.material ? "" : (state.doc?.text || ""),
    material_id: state.material?.id || null,
    surface: "ask",
    context_snapshot: state.material ? buildSnapshot({
      surface: "ask",
      object_type: "material",
      object_id: String(state.material.id),
      title: state.material.title || "",
      surrounding: {
        kind: state.material.kind || "",
        chars: state.material.chars || 0,
      },
      provenance: { page: "ask", via: "material-picker" },
    }) : null,
  };

  if (state.messages.length === 0) dom.inner.innerHTML = "";
  const shown = message
    + (state.image ? `\n［图片：${state.image.name}］` : "")
    + (state.doc ? `\n［文档：${state.doc.name}］` : "")
    + (state.material ? `\n［资料：${state.material.title}］` : "");
  addUserBlock(shown);
  state.messages.push({ role: "user", content: { text: message } });

  dom.input.value = "";
  dom.input.style.height = "auto";
  state.image = null;
  state.doc = null;
  state.material = null;
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
  state.runId = "";
  state.usedTools = new Set();
  state.usedVision = false;
  state.thinkingDirty = false;
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
        state.runId = String(event.data?.run_id || "");
        if (id && state.convId !== id) {
          state.convId = id;
          history.replaceState(null, "", `#/ask/${id}`);
        }
      } else if (event.kind === "plan") {
        renderPlan(block, event.data?.steps || [], !!event.data?.truncated);
        setAssistantStatus(block, "按计划执行", true);
      } else if (event.kind === "plan_update") {
        renderPlan(block, event.data?.steps || []);
      } else if (event.kind === "check") {
        showCheck(block, event.data || {});
      } else if (event.kind === "rewrite") {
        state.text = String(event.data?.text || "");
        block.body.hidden = !state.text;
        paintAssistant(true);
        setAssistantStatus(block, "自检后已重写", true);
      } else if (event.kind === "thinking") {
        state.thinking += event.text || "";
        state.thinkingDirty = true;
        if (block.thinkingEl.hidden) {
          block.thinkingEl.hidden = false;
          block.thinkingEl.open = true;     // 先展开：让人看到推理在推进
        }
        setAssistantStatus(block, "思考中", true);
        schedulePaint();
      } else if (event.kind === "activity") {
        if (event.text) setAssistantStatus(block, event.text, true);
      } else if (event.kind === "text") {
        const firstText = !state.text;
        state.text += event.text || "";
        if (firstText && state.thinking) {
          block.thinkingEl.open = false;    // 正文开始：思考收起成一行，不挤占答案
        }
        setAssistantStatus(block, state.text ? "正在写" : "思考中", true);
        schedulePaint();
      } else if (event.kind === "tool_start") {
        addToolRow(block, event.data?.name || "tool", event.data?.input || {},
          event.data?.goal || "", event.data?.step);
        setAssistantStatus(block, event.data?.goal || "在查本地记录", true);
      } else if (event.kind === "tool_end") {
        updateToolPreview(block, event.data?.name || "", event.data?.preview || "",
          event.data?.ok !== false, event.data?.step);
        if (event.data?.ok === false) {
          setAssistantStatus(block, "这步没成功，正在换路", true);
        }
      } else if (event.kind === "vision") {
        if (typeof event.data?.used_vision === "boolean") {
          state.usedVision = event.data.used_vision;
        } else {
          setAssistantStatus(block, "正在看图", true);
        }
      } else if (event.kind === "done") {
        const finalText = String(event.data?.text || state.text || "");
        if (finalText) state.text = finalText;
        if (event.data?.thinking) {
          state.thinking = String(event.data.thinking);
          state.thinkingDirty = true;
        }
        paintAssistant(true);
        if (event.data?.truncated) {
          setAssistantStatus(block, "回答达到上限，末尾可能被截断");
        }
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
      state.messages.push({ role: "assistant", content: {
        text: state.text, thinking: state.thinking, run_id: state.runId || undefined } });
    }
    if (state.runId) attachReplay(block, state.runId);
  } else {
    setAssistantStatus(block, note || "已停止");
    if (state.text) {
      paintAssistant(true);
      state.messages.push({ role: "assistant", content: {
        text: state.text, thinking: state.thinking, run_id: state.runId || undefined } });
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
