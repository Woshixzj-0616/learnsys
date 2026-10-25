// 问一问页面入口：生命周期、事件绑定、插件联动。
import { api } from "../../api.js";
import { toast } from "../../ui.js";
import { MODE_NAMES, ctxRef, dom, resetState, setCtx, setDom, setSubDefault, state } from "./state.js";
import { renderThread } from "./thread.js";
import { loadConversations, newConversation, openConversation } from "./conversations.js";
import { closeMaterialPicker, loadMaterialPicker, onPickerKey, openMaterialPicker } from "./materials.js";
import { pickFile, renderAttachments, updateSendButton } from "./attachments.js";
import { loadDeepStatus, runDeepAnalysis } from "./deep.js";
import { sendMessage } from "./composer.js";
import { stopStreaming } from "./stream.js";


export async function mount(ctx) {
  resetState();
  setCtx(ctx);
  state.mounted = true;
  state.convId = Number(ctx.params[0]) || null;

  setDom({
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
    deepRun: ctx.root.querySelector("#deep-run"),
  });

  dom.mode.value = MODE_NAMES[state.mode] ? state.mode : "explain";
  state.mode = dom.mode.value;
  bindEvents();
  updateSendButton();
  window.addEventListener("learnsys:answer-think", onAnswerThink);

  await loadConversations();
  await loadDeepStatus();
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
  const recordingId = Number(ctx.query?.get("recording") || 0);
  if (recordingId) {
    try {
      const data = await api.get(`/api/recordings/${recordingId}`);
      state.recording = {
        id: data.id, title: data.title, chars: data.chars, duration: data.duration,
      };
      renderAttachments();
      updateSendButton();
      dom.status.textContent = `已挂录像：${data.title}`;
    } catch (error) {
      toast(error.message || "录像没挂上", "err");
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

export function bindEvents() {
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
  dom.deepRun?.addEventListener("click", runDeepAnalysis);

  dom.fileImage.addEventListener("change", () => pickFile(dom.fileImage, "image"));
  dom.fileDoc.addEventListener("change", () => pickFile(dom.fileDoc, "doc"));

  dom.attachRow.addEventListener("click", (event) => {
    const pin = event.target.closest("button[data-pin]");
    if (pin?.dataset.pin === "material") {
      state.materialPinned = !state.materialPinned;
      renderAttachments();
      dom.status.textContent = state.materialPinned
        ? "资料已固定：之后每一轮都会带上"
        : "资料已取消固定：这一轮用完就撤";
      return;
    }
    const button = event.target.closest("button[data-remove]");
    if (!button) return;
    if (button.dataset.remove === "image") state.image = null;
    if (button.dataset.remove === "doc") state.doc = null;
    if (button.dataset.remove === "material") {
      state.material = null;
      state.materialPinned = false;
    }
    if (button.dataset.remove === "recording") state.recording = null;
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
