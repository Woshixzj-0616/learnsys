// 资料库列表层：拉取、统计条、列表渲染与筛选控件。
import { api } from "../api.js";
import { escapeHtml } from "../ui.js";

export const KIND_LABEL = {
  pdf: "PDF", docx: "Word", pptx: "PPT", txt: "TXT", md: "Markdown", note: "笔记",
};

export async function loadList(app) {
  app.nodes.list.innerHTML = '<div class="empty">正在读资料库…</div>';
  try {
    const params = new URLSearchParams({ status: app.status, limit: "200" });
    if (app.kind) params.set("kind", app.kind);
    if (app.query) params.set("q", app.query);
    const data = await api.get(`/api/materials?${params}`);
    app.items = Array.isArray(data.items) ? data.items : [];
    app.counts = data.counts || app.counts;
    renderStats(app);
    renderList(app);
  } catch (error) {
    app.nodes.list.innerHTML = `<div class="empty"><strong>资料库没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

export function renderStats(app) {
  app.nodes.stats.innerHTML = [
    ["资料", app.counts.active ?? 0],
    ["回收站", app.counts.trashed ?? 0],
    ["当前结果", app.items.length],
  ].map(([label, value]) => `
    <div class="review-chip"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
}

export function renderList(app) {
  const items = app.items;
  if (!items.length) {
    app.nodes.list.innerHTML = `<div class="empty"><strong>${app.status === "trashed" ? "回收站是空的" : "还没有资料"}</strong>
      ${app.status === "trashed" ? "删掉的资料会先来这儿。" : "点右上角「导入资料」，或把 PDF / PPT 拖进来。"}</div>`;
    return;
  }
  app.nodes.list.innerHTML = items.map((item) => `
    <button class="mat-item ${app.selected?.id === item.id ? "active" : ""}" type="button"
            data-material="${item.id}">
      <span class="mat-item-kind ${escapeHtml(item.kind)}">${escapeHtml(KIND_LABEL[item.kind] || item.kind)}</span>
      <span class="mat-item-main">
        <strong>${escapeHtml(item.title)}</strong>
        <small>${escapeHtml(item.chars)} 字${item.pages ? ` · ${item.pages} 页` : ""}
          ${item.course ? ` · ${escapeHtml(item.course)}` : ""}
          ${item.page ? ` · 命中第 ${item.page} 页` : ""}</small>
        ${item.snippet ? `<em>${escapeHtml(item.snippet)}</em>` : (item.preview ? `<em>${escapeHtml(item.preview)}</em>` : "")}
      </span>
      <span class="mat-item-date">${escapeHtml(String(item.updated_at || "").slice(0, 10))}</span>
    </button>`).join("");
}

export function bindList(app) {
  const nodes = app.nodes;
  nodes.search.addEventListener("input", () => {
    clearTimeout(nodes.search._timer);
    nodes.search._timer = setTimeout(() => {
      app.query = nodes.search.value.trim();
      app.loadList();
    }, 220);
  });
  nodes.kind.addEventListener("change", () => {
    app.kind = nodes.kind.value;
    app.loadList();
  });
  nodes.trash.addEventListener("click", () => {
    app.status = app.status === "active" ? "trashed" : "active";
    nodes.trash.classList.toggle("active", app.status === "trashed");
    nodes.trash.textContent = app.status === "active" ? "回收站" : "返回资料";
    app.selected = null;
    app.renderDetailEmpty();
    app.loadList();
  });
  nodes.list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-material]");
    if (!button) return;
    app.selectMaterial(Number(button.dataset.material));
  });
}
