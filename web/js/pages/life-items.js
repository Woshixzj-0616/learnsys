// 生活事务箱：单层待办 + 作息/备注的一行轻记录；不建子任务、不做重复任务。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

const KIND_LABEL = { todo: "待办", habit: "作息记录", note: "备注" };

let items = [];
let nodes = {};
let filter = "open";
let editingId = 0;
let onCounts = () => {};

export async function mount(ctx, callback) {
  onCounts = typeof callback === "function" ? callback : () => {};
  nodes = {
    stats: ctx.root.querySelector("#life-item-stats"),
    list: ctx.root.querySelector("#life-item-list"),
    filters: ctx.root.querySelector("#life-item-filters"),
    form: ctx.root.querySelector("#life-item-form"),
    formTitle: ctx.root.querySelector("#life-item-form-title"),
    title: ctx.root.querySelector("#li-title"),
    kind: ctx.root.querySelector("#li-kind"),
    due: ctx.root.querySelector("#li-due"),
    valueField: ctx.root.querySelector("#li-value-field"),
    value: ctx.root.querySelector("#li-value"),
    note: ctx.root.querySelector("#li-note"),
    cancel: ctx.root.querySelector("#li-cancel"),
  };
  ctx.root.querySelector("#life-item-new").addEventListener("click", () => openForm());
  nodes.cancel.addEventListener("click", closeForm);
  nodes.form.addEventListener("submit", onSubmit);
  nodes.kind.addEventListener("change", syncValueField);
  nodes.filters.addEventListener("click", onFilterClick);
  nodes.list.addEventListener("click", onListClick);
  syncValueField();
  await load();
}

export function unmount() {}

async function load() {
  try {
    const data = await api.get(`/api/life/items?status=${filter}`);
    items = Array.isArray(data.items) ? data.items : [];
    renderList();
    const counts = data.counts || {};
    nodes.stats.textContent = `待办 ${Number(counts.open || 0)}`
      + ` · 逾期 ${Number(counts.overdue || 0)}`;
    onCounts(counts);
  } catch (error) {
    nodes.list.innerHTML = `<div class="empty"><strong>事务没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function localToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
    + `-${String(now.getDate()).padStart(2, "0")}`;
}

function dueInfo(due) {
  const text = String(due || "");
  if (!text) return { text: "不限期", tone: "" };
  const today = localToday();
  if (text < today) {
    const days = Math.round((Date.parse(today) - Date.parse(text)) / 86400000);
    return { text: `逾期 ${days} 天`, tone: "is-overdue" };
  }
  if (text === today) return { text: "今天", tone: "is-today" };
  return { text, tone: "" };
}

function renderList() {
  if (!items.length) {
    nodes.list.innerHTML = `<div class="empty"><strong>这里还没有事务</strong>
      点上面「新建事务」；到期的事务会出现在今日页提醒里。</div>`;
    return;
  }
  nodes.list.innerHTML = items.map((item) => {
    const due = dueInfo(item.due_date);
    const kind = KIND_LABEL[item.kind] || item.kind;
    const value = item.value
      ? `<div class="life-item-value">${escapeHtml(item.value)}</div>` : "";
    const note = item.note
      ? `<div class="life-item-note">${escapeHtml(item.note)}</div>` : "";
    const actions = [];
    if (item.status === "open") {
      actions.push(`<button class="btn btn-primary" type="button" data-done="${item.id}">完成</button>`);
      actions.push(`<button class="btn btn-quiet" type="button" data-archive="${item.id}">归档</button>`);
    } else if (item.status === "done") {
      actions.push(`<button class="btn btn-quiet" type="button" data-reopen="${item.id}">重开</button>`);
      actions.push(`<button class="btn btn-quiet" type="button" data-archive="${item.id}">归档</button>`);
    } else {
      actions.push(`<button class="btn btn-quiet" type="button" data-reopen="${item.id}">重开</button>`);
    }
    actions.push(`<button class="btn btn-quiet" type="button" data-edit="${item.id}">编辑</button>`);
    actions.push(`<button class="btn btn-quiet" type="button" data-del="${item.id}">删除</button>`);
    return `
      <div class="life-item${item.status !== "open" ? " is-muted" : ""}"
           data-item-id="${item.id}">
        <div class="life-item-head">
          <strong>${escapeHtml(item.title)}</strong>
          <span class="life-badge">${escapeHtml(kind)}</span>
          <span class="life-due ${due.tone}">${escapeHtml(due.text)}</span>
        </div>
        ${value}${note}
        <div class="life-item-actions">${actions.join("")}</div>
      </div>`;
  }).join("");
}

function syncValueField() {
  nodes.valueField.hidden = nodes.kind.value === "todo";
}

function openForm(item = null) {
  editingId = item ? item.id : 0;
  nodes.formTitle.textContent = item ? "编辑事务" : "新建事务";
  nodes.title.value = item ? item.title : "";
  nodes.kind.value = item ? item.kind : "todo";
  nodes.due.value = item ? (item.due_date || "") : "";
  nodes.value.value = item ? (item.value || "") : "";
  nodes.note.value = item ? (item.note || "") : "";
  syncValueField();
  nodes.form.hidden = false;
  nodes.title.focus();
}

function closeForm() {
  nodes.form.hidden = true;
  editingId = 0;
}

function payload() {
  const data = {
    title: nodes.title.value.trim(),
    kind: nodes.kind.value,
    due_date: nodes.due.value || "",
    note: nodes.note.value.trim(),
    value: nodes.kind.value === "todo" ? "" : nodes.value.value.trim(),
  };
  return data;
}

async function onSubmit(event) {
  event.preventDefault();
  const data = payload();
  if (!data.title) {
    toast("事务标题不能为空", "err");
    return;
  }
  try {
    if (editingId) await api.patch(`/api/life/items/${editingId}`, data);
    else await api.post("/api/life/items", data);
    toast("已保存");
    closeForm();
    await load();
  } catch (error) {
    toast(error.message || error, "err");
  }
}

async function act(path) {
  try {
    await api.post(path);
    await load();
  } catch (error) {
    toast(error.message || error, "err");
  }
}

function onFilterClick(event) {
  const button = event.target.closest("[data-status]");
  if (!button) return;
  filter = button.dataset.status;
  for (const node of nodes.filters.querySelectorAll(".life-filter")) {
    node.classList.toggle("is-active", node === button);
  }
  load();
}

function onListClick(event) {
  const done = event.target.closest("[data-done]");
  if (done) return act(`/api/life/items/${done.dataset.done}/done`);
  const reopen = event.target.closest("[data-reopen]");
  if (reopen) return act(`/api/life/items/${reopen.dataset.reopen}/reopen`);
  const archive = event.target.closest("[data-archive]");
  if (archive) return act(`/api/life/items/${archive.dataset.archive}/archive`);

  const edit = event.target.closest("[data-edit]");
  if (edit) {
    const item = items.find((row) => String(row.id) === edit.dataset.edit);
    if (item) openForm(item);
    return;
  }
  const del = event.target.closest("[data-del]");
  if (del) {
    const item = items.find((row) => String(row.id) === del.dataset.del);
    if (!item) return;
    if (!confirm(`删除事务「${item.title}」？删除后不能恢复。`)) return;
    api.del(`/api/life/items/${item.id}`)
      .then(() => { toast("已删除"); return load(); })
      .catch((error) => toast(error.message || error, "err"));
  }
}
