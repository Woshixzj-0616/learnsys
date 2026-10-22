// 资料选择器：搜索资料库、挂到这一轮。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";
import { state, dom } from "./state.js";
import { renderAttachments, updateSendButton } from "./attachments.js";


export function onPickerKey(event) {
  if (event.key === "Escape" && !dom.materialPicker.hidden) closeMaterialPicker();
}

export async function openMaterialPicker() {
  if (state.streaming) {
    toast("先等这一轮写完再挂资料");
    return;
  }
  dom.materialPicker.hidden = false;
  dom.materialSearch.value = "";
  await loadMaterialPicker("");
  dom.materialSearch.focus();
}

export function closeMaterialPicker() {
  dom.materialPicker.hidden = true;
}

export async function loadMaterialPicker(query) {
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
