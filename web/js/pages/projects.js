// 项目：登记路径/状态/下一步/风险；生成只含指针的 HANDOFF，不写回仓库。
import { api } from "../api.js";
import { escapeHtml, relative, toast } from "../ui.js";

const STATUS_LABEL = { active: "进行中", paused: "暂停", archived: "已归档" };

let editingId = 0;
let items = [];
let nodes = {};

export async function mount(ctx) {
  ctx.setSub("登记路径与状态，生成交接页；不复制仓库内容，不写回仓库");
  nodes = {
    list: ctx.root.querySelector("#project-list"),
    stats: ctx.root.querySelector("#project-stats"),
    form: ctx.root.querySelector("#project-form"),
    title: ctx.root.querySelector("#project-form-title"),
    name: ctx.root.querySelector("#pf-name"),
    repo: ctx.root.querySelector("#pf-repo"),
    status: ctx.root.querySelector("#pf-status"),
    next: ctx.root.querySelector("#pf-next"),
    risk: ctx.root.querySelector("#pf-risk"),
    cancel: ctx.root.querySelector("#pf-cancel"),
  };
  ctx.root.querySelector("#project-new").addEventListener("click", () => openForm());
  nodes.cancel.addEventListener("click", closeForm);
  nodes.form.addEventListener("submit", onSubmit);
  nodes.list.addEventListener("click", onListClick);
  await load();
}

export function unmount() {}

async function load() {
  try {
    const data = await api.get("/api/projects?status=all");
    items = Array.isArray(data.items) ? data.items : [];
    renderStats();
    renderList();
  } catch (error) {
    nodes.list.innerHTML = `<div class="empty"><strong>项目清单没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function renderStats() {
  const count = (status) => items.filter((item) => item.status === status).length;
  nodes.stats.innerHTML = [
    ["进行中", count("active")],
    ["暂停", count("paused")],
    ["已归档", count("archived")],
  ].map(([label, value]) => `
    <div class="review-chip"><span>${escapeHtml(label)}</span><strong>${value}</strong></div>
  `).join("");
}

function renderList() {
  if (!items.length) {
    nodes.list.innerHTML = `<div class="empty"><strong>还没有项目</strong>
      点右上角「新建项目」，填名称和仓库路径即可；交接页会按路径去读文档指针。</div>`;
    return;
  }
  nodes.list.innerHTML = items.map((item) => {
    const status = STATUS_LABEL[item.status] || item.status;
    const repo = String(item.repo_path || "").trim();
    const repoLine = repo
      ? `<span class="project-repo ${item.repo_exists ? "" : "bad"}">${escapeHtml(repo)}${item.repo_exists ? "" : "（路径失效）"}</span>`
      : '<span class="hint">未填仓库路径</span>';
    return `
      <article class="project-card status-${escapeHtml(item.status || "active")}" data-id="${item.id}">
        <div class="project-card-head">
          <span class="project-status ${escapeHtml(item.status || "active")}">${escapeHtml(status)}</span>
          <h3>${escapeHtml(item.name)}</h3>
          <span class="hint">${escapeHtml(relative(item.updated_at) || "")}</span>
        </div>
        <div class="project-card-meta">${repoLine}</div>
        <p class="project-next"><b>下一步</b> ${escapeHtml(item.next_step || "未填写")}</p>
        ${item.risk ? `<p class="project-risk"><b>风险</b> ${escapeHtml(item.risk)}</p>` : ""}
        <div class="project-actions">
          <button class="btn btn-quiet" type="button" data-act="edit">编辑</button>
          <button class="btn" type="button" data-act="handoff">生成交接</button>
          <button class="btn btn-quiet" type="button" data-act="open">看交接</button>
          ${item.status === "archived" ? "" :
            '<button class="btn btn-danger" type="button" data-act="archive">归档</button>'}
        </div>
        <pre class="project-handoff" hidden></pre>
        <div class="project-path hint" hidden></div>
      </article>`;
  }).join("");
}

function findItem(card) {
  return items.find((item) => item.id === Number(card.dataset.id || 0));
}

async function onListClick(event) {
  const card = event.target.closest(".project-card");
  const button = event.target.closest("[data-act]");
  if (!card || !button) return;
  const item = findItem(card);
  if (!item) return;
  const action = button.dataset.act;
  if (action === "edit") {
    openForm(item);
  } else if (action === "handoff") {
    await generateHandoff(card, item, button);
  } else if (action === "open") {
    await openHandoff(card, item, button);
  } else if (action === "archive") {
    await archive(card, item, button);
  }
}

async function generateHandoff(card, item, button) {
  button.disabled = true;
  try {
    const data = await api.post(`/api/projects/${item.id}/handoff`, {});
    showPreview(card, data.text, data.path);
    toast("交接页已生成", "ok");
    await load();
    const again = nodes.list.querySelector(`.project-card[data-id="${item.id}"]`);
    if (again) showPreview(again, data.text, data.path);
  } catch (error) {
    toast(error.message || "生成失败", "err");
  } finally {
    button.disabled = false;
  }
}

async function openHandoff(card, item, button) {
  button.disabled = true;
  try {
    const data = await api.get(`/api/projects/${item.id}/handoff`);
    showPreview(card, data.text, data.path);
  } catch (error) {
    toast(error.message || "还没有生成交接页", "err");
  } finally {
    button.disabled = false;
  }
}

function showPreview(card, text, path) {
  const pre = card.querySelector(".project-handoff");
  const line = card.querySelector(".project-path");
  if (!pre || !line) return;
  pre.hidden = false;
  pre.textContent = String(text || "").split("\n").slice(0, 40).join("\n");
  line.hidden = false;
  line.textContent = `文件：${path || ""}`;
}

async function archive(card, item, button) {
  if (!window.confirm(`归档「${item.name}」？归档后默认列表不再显示，记录与交接页都保留。`)) {
    return;
  }
  button.disabled = true;
  try {
    await api.post(`/api/projects/${item.id}/archive`, {});
    toast("已归档", "ok");
    await load();
  } catch (error) {
    toast(error.message || "归档失败", "err");
    button.disabled = false;
  }
}

function openForm(item = null) {
  editingId = item ? item.id : 0;
  nodes.title.textContent = item ? `编辑「${item.name}」` : "新建项目";
  nodes.name.value = item?.name || "";
  nodes.repo.value = item?.repo_path || "";
  nodes.status.value = item?.status || "active";
  nodes.next.value = item?.next_step || "";
  nodes.risk.value = item?.risk || "";
  nodes.form.hidden = false;
  nodes.form.scrollIntoView({ behavior: "smooth", block: "nearest" });
  nodes.name.focus();
}

function closeForm() {
  editingId = 0;
  nodes.form.hidden = true;
  nodes.form.reset();
}

async function onSubmit(event) {
  event.preventDefault();
  const body = {
    name: nodes.name.value.trim(),
    repo_path: nodes.repo.value.trim(),
    status: nodes.status.value,
    next_step: nodes.next.value.trim(),
    risk: nodes.risk.value.trim(),
  };
  if (!body.name) {
    toast("项目名不能为空", "err");
    return;
  }
  const submit = nodes.form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    if (editingId) {
      await api.patch(`/api/projects/${editingId}`, body);
    } else {
      await api.post("/api/projects", body);
    }
    toast(editingId ? "已更新" : "已新建", "ok");
    closeForm();
    await load();
  } catch (error) {
    toast(error.message || "保存失败", "err");
  } finally {
    submit.disabled = false;
  }
}
