// 设置页：长期记忆、候选、画像、历史对话检索。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

const MEMORY_KINDS = [
  ["preference", "偏好"], ["rule", "规矩"], ["identity", "身份"],
  ["goal", "目标"], ["constraint", "约束"], ["project", "项目"],
];

function kindOptions(selected) {
  return MEMORY_KINDS.map(([value, label]) =>
    `<option value="${value}" ${value === selected ? "selected" : ""}>${label}</option>`
  ).join("");
}

export function bindMemory() {
  document.getElementById("memory-add")?.addEventListener("click", addMemory);
  const input = document.getElementById("memory-input");
  input?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addMemory();
    }
  });
  document.getElementById("memory-list")?.addEventListener("click", onMemoryAction);
  document.getElementById("memory-list")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.target.matches(".memory-text")) return;
    event.preventDefault();          // 别让回车顺手提交整页设置
    event.target.closest(".memory-row")?.querySelector("[data-act='save']")?.click();
  });
  document.getElementById("memory-candidates")?.addEventListener("click", onCandidateAction);
  document.getElementById("memory-compile")?.addEventListener("click", compileProfile);
  document.getElementById("archive-search")?.addEventListener("click", searchArchive);
  document.getElementById("archive-query")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchArchive();
    }
  });
}

export async function loadMemories() {
  const list = document.getElementById("memory-list");
  if (!list) return;
  try {
    const data = await api.get("/api/memory");
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      list.innerHTML = '<div class="hint">还没有记忆。Agent 听到「以后都…」会自动记；也可以在上面手动加。</div>';
      return;
    }
    list.innerHTML = items.map((item) => `
      <div class="memory-row" data-id="${item.id}">
        <input class="input memory-text" value="${escapeHtml(item.content)}" maxlength="500">
        <select class="input memory-kind">${kindOptions(item.kind)}</select>
        <input class="input memory-scope" value="${escapeHtml(item.scope || "global")}"
               title="作用域：global / exam:cet6 / course:… / project:…">
        <input class="input memory-confidence" type="number" min="0" max="1" step="0.05"
               value="${Number(item.confidence ?? 0.5).toFixed(2)}" title="置信度">
        <span class="hint">${escapeHtml(item.source || "user")} · ${escapeHtml((item.evidence || "").slice(0, 80))}</span>
        <button class="btn btn-quiet" type="button" data-act="save">保存</button>
        <button class="btn btn-quiet" type="button" data-act="del">删除</button>
      </div>`).join("");
  } catch (error) {
    list.innerHTML = `<div class="empty">记忆没读出来：${escapeHtml(error.message || error)}</div>`;
  }
}

async function addMemory() {
  const input = document.getElementById("memory-input");
  const content = input?.value.trim() || "";
  if (!content) return;
  const kind = document.getElementById("memory-kind")?.value || "preference";
  const scope = document.getElementById("memory-scope")?.value.trim() || "global";
  try {
    const result = await api.post("/api/memory", { content, kind, scope });
    input.value = "";
    toast(result.message || "已记住", "ok");
    await loadMemories();
  } catch (error) {
    toast(error.message || "没记住", "err");
  }
}

async function onMemoryAction(event) {
  const button = event.target.closest("button[data-act]");
  if (!button) return;
  const row = button.closest(".memory-row");
  const id = Number(row?.dataset.id || 0);
  if (!id) return;
  if (button.dataset.act === "del") {
    try {
      const result = await api.del(`/api/memory/${id}`);
      toast(result.message || "已忘掉", "ok");
      await loadMemories();
    } catch (error) {
      toast(error.message || "删除失败", "err");
    }
    return;
  }
  const content = row.querySelector(".memory-text")?.value.trim() || "";
  if (!content) return;
  const kind = row.querySelector(".memory-kind")?.value || "preference";
  const scope = row.querySelector(".memory-scope")?.value.trim() || "global";
  const confidence = Number(row.querySelector(".memory-confidence")?.value || 0.5);
  try {
    const result = await api.post(`/api/memory/${id}`, { content, kind, scope, confidence });
    toast(result.message || "已更新", "ok");
    await loadMemories();
  } catch (error) {
    toast(error.message || "更新失败", "err");
  }
}

export async function loadCandidates() {
  const box = document.getElementById("memory-candidates");
  if (!box) return;
  try {
    const data = await api.get("/api/memory/candidates");
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      box.innerHTML = '<div class="hint">没有待确认的候选。</div>';
      return;
    }
    box.innerHTML = items.map((item) => `
      <div class="memory-row" data-id="${item.id}">
        <span class="memory-text">${escapeHtml(item.content)}</span>
        <span class="hint">${escapeHtml(item.kind)} · ${escapeHtml(item.scope)} ·
          ${Number(item.confidence ?? 0).toFixed(2)} · ${escapeHtml(item.evidence || "")}</span>
        <button class="btn btn-quiet" type="button" data-act="promote">采纳</button>
        <button class="btn btn-quiet" type="button" data-act="ignore">忽略</button>
      </div>`).join("");
  } catch (error) {
    box.innerHTML = `<div class="empty">候选没读出来：${escapeHtml(error.message || error)}</div>`;
  }
}

async function onCandidateAction(event) {
  const button = event.target.closest("button[data-act]");
  if (!button) return;
  const id = Number(button.closest(".memory-row")?.dataset.id || 0);
  if (!id) return;
  const action = button.dataset.act === "promote" ? "promote" : "archive";
  try {
    const result = await api.post(`/api/memory/${id}/${action}`, {});
    toast(result.message || "已处理", "ok");
    await loadMemories();
    await loadCandidates();
  } catch (error) {
    toast(error.message || "处理失败", "err");
  }
}

export async function loadProfileStatus() {
  const label = document.getElementById("memory-profile-status");
  if (!label) return;
  try {
    const data = await api.get("/api/memory/profile");
    label.textContent = data.stale ? "画像已过期，建议重新编译" : "画像是最新的";
  } catch (error) {
    label.textContent = "画像状态没读出来";
  }
}

async function compileProfile() {
  try {
    const result = await api.post("/api/memory/profile/compile", {});
    toast(`画像已编译：${result.facts} 条`, "ok");
    await loadProfileStatus();
  } catch (error) {
    toast(error.message || "编译失败", "err");
  }
}

async function searchArchive() {
  const input = document.getElementById("archive-query");
  const box = document.getElementById("archive-results");
  const query = input?.value.trim() || "";
  if (!query || !box) return;
  box.innerHTML = '<div class="hint">正在查…</div>';
  try {
    const data = await api.get(`/api/memory/archive/search?q=${encodeURIComponent(query)}&limit=8`);
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      box.innerHTML = '<div class="hint">没有找到。</div>';
      return;
    }
    box.innerHTML = items.map((item) => `
      <div class="memory-row">
        <div>
          <div class="hint">${escapeHtml((item.at || "").slice(0, 10))} ·
            ${escapeHtml(item.source)} · ${escapeHtml(item.role)}</div>
          <div>${escapeHtml(item.snippet)}</div>
          <code class="hint">${escapeHtml(item.anchor)}</code>
        </div>
      </div>`).join("");
  } catch (error) {
    box.innerHTML = `<div class="empty">检索失败：${escapeHtml(error.message || error)}</div>`;
  }
}
