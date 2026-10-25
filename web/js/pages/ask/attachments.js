// 附件与发送按钮：图片 / 一次性文档 / 资料库三选一。
import { api, upload } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";
import { state, dom } from "./state.js";


export function updateSendButton() {
  const hasText = dom.input.value.trim().length > 0;
  dom.send.disabled = state.streaming
    || (!hasText && !state.image && !state.doc && !state.material && !state.recording);
}

export async function pickFile(input, kind) {
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
      state.materialPinned = false;
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

export function renderAttachments() {
  const items = [];
  if (state.image) {
    items.push(`<span class="attach-chip">图片 · ${escapeHtml(state.image.name)}
      <button type="button" data-remove="image" aria-label="移除图片">×</button></span>`);
  }
  if (state.doc) {
    items.push(`<span class="attach-chip">文档 · ${escapeHtml(state.doc.name)} · ${state.doc.chars} 字
      <button type="button" data-remove="doc" aria-label="移除文档">×</button></span>`);
  }
  if (state.recording) {
    items.push(`<span class="attach-chip">
      <span class="attach-kind">上下文 · 录像</span> ${escapeHtml(state.recording.title)}${state.recording.chars ? ` · ${state.recording.chars} 字` : ""}
      <button type="button" data-remove="recording" aria-label="移除录像">×</button></span>`);
  }
  if (state.material) {
    const pinned = state.materialPinned;
    items.push(`<span class="attach-chip${pinned ? " is-pinned" : ""}">
      <span class="attach-kind">上下文 · 资料</span> ${escapeHtml(state.material.title)} · ${state.material.chars} 字
      <button type="button" data-pin="material" aria-pressed="${pinned}"
        title="${pinned ? "已固定：每一轮都会带上这份资料" : "固定这份资料，连续几轮都带上"}">${pinned ? "已固定" : "固定"}</button>
      <button type="button" data-remove="material" aria-label="移除资料">×</button></span>`);
  }
  dom.attachRow.innerHTML = items.join("");
  dom.attachRow.hidden = items.length === 0;
}
