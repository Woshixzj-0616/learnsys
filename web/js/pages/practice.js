// 经验库：三格卡（场景 / 坑或有效点 / 下次），可搜索、按项目筛、记录用到次数。
// 不做每日复习；AI 起草的草稿通过 sessionStorage["practice-draft"] 预填。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

const KIND_LABEL = { pitfall: "踩坑", good_practice: "有效做法" };
const SOURCE_LABEL = {
  ask: "问一问", agent_task: "派活", code: "代码调试", manual: "手动",
};

let items = [];
let projects = [];
let editingId = 0;
let searchTimer = null;
let nodes = {};

export async function mount(ctx) {
  ctx.setSub("场景 / 坑或有效点 / 下次怎么做；技术原因可以留给 AI 补");
  editingId = 0;
  items = [];
  nodes = {
    q: ctx.root.querySelector("#practice-q"),
    project: ctx.root.querySelector("#practice-project"),
    formProject: ctx.root.querySelector("#practice-form-project"),
    newButton: ctx.root.querySelector("#practice-new"),
    formPanel: ctx.root.querySelector("#practice-form-panel"),
    formTitle: ctx.root.querySelector("#practice-form-title"),
    cancel: ctx.root.querySelector("#practice-cancel"),
    save: ctx.root.querySelector("#practice-save"),
    status: ctx.root.querySelector("#practice-status"),
    title: ctx.root.querySelector("#practice-title"),
    scene: ctx.root.querySelector("#practice-scene"),
    pitfall: ctx.root.querySelector("#practice-pitfall"),
    next: ctx.root.querySelector("#practice-next"),
    why: ctx.root.querySelector("#practice-why"),
    evidence: ctx.root.querySelector("#practice-evidence"),
    tags: ctx.root.querySelector("#practice-tags"),
    list: ctx.root.querySelector("#practice-list"),
    count: ctx.root.querySelector("#practice-count"),
    hint: ctx.root.querySelector("#practice-hint"),
  };
  bind();
  await loadProjects();
  // 项目卡「经验 N」带 #/practice?project=ID 进来时，直接筛到该项目。
  const initialProject = Number(ctx.query?.get?.("project") || 0);
  if (initialProject && projects.some((item) => Number(item.id) === initialProject)) {
    nodes.project.value = String(initialProject);
  }
  await load();
  const draft = sessionStorage.getItem("practice-draft");
  if (draft) {
    sessionStorage.removeItem("practice-draft");
    try {
      openForm(null, JSON.parse(draft));
    } catch {
      // 草稿坏了就忽略，不挡页面
    }
  }
}

function bind() {
  nodes.newButton.addEventListener("click", () => openForm());
  nodes.cancel.addEventListener("click", closeForm);
  nodes.save.addEventListener("click", save);
  nodes.list.addEventListener("click", onListClick);
  nodes.project.addEventListener("change", load);
  nodes.q.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 250);
  });
}

async function loadProjects() {
  try {
    const data = await api.get("/api/projects");
    projects = Array.isArray(data.items) ? data.items : [];
  } catch {
    projects = [];
  }
  const options = ['<option value="0">全部项目</option>'];
  const formOptions = ['<option value="0">不关联项目</option>'];
  for (const project of projects) {
    options.push(`<option value="${project.id}">${escapeHtml(project.name)}</option>`);
    formOptions.push(`<option value="${project.id}">${escapeHtml(project.name)}</option>`);
  }
  nodes.project.innerHTML = options.join("");
  nodes.formProject.innerHTML = formOptions.join("");
}

async function load() {
  nodes.list.innerHTML = '<div class="empty">正在读经验库…</div>';
  try {
    const query = new URLSearchParams({
      q: nodes.q.value.trim(),
      project_id: nodes.project.value || "0",
    });
    const data = await api.get(`/api/practice?${query}`);
    items = Array.isArray(data.items) ? data.items : [];
    renderList();
  } catch (error) {
    nodes.list.innerHTML = `<div class="empty"><strong>经验库没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function projectName(id) {
  return (projects.find((item) => item.id === Number(id || 0)) || {}).name || "";
}

function renderList() {
  nodes.count.textContent = `经验 ${items.length} 条`;
  nodes.hint.textContent = items.length ? "按最近更新排序" : "";
  if (!items.length) {
    nodes.list.innerHTML = `<div class="empty"><strong>还没有经验</strong>
      <p>下次让 AI 改完东西、或问完一个问题，从结果里点「记一条经验」，
      这里就会慢慢长出你自己的经验。</p></div>`;
    return;
  }
  nodes.list.innerHTML = items.map(cardHtml).join("");
}

function cardHtml(note) {
  const project = projectName(note.project_id);
  const source = SOURCE_LABEL[note.source] || "";
  return `
    <article class="practice-card" data-id="${note.id}">
      <div class="practice-card-head">
        <span class="practice-kind-badge ${escapeHtml(note.kind)}">${KIND_LABEL[note.kind] || "经验"}</span>
        <h3>${escapeHtml(note.title)}</h3>
        <span class="hint">${note.used_count ? `用到 ${note.used_count} 次` : "还没用过"}</span>
      </div>
      <div class="practice-grid">
        <div><span class="practice-label">场景</span><p>${escapeHtml(note.scene)}</p></div>
        <div><span class="practice-label">${note.kind === "good_practice" ? "有效点" : "坑"}</span>
          <p>${escapeHtml(note.pitfall)}</p></div>
        <div><span class="practice-label">下次</span><p>${escapeHtml(note.next_time)}</p></div>
      </div>
      ${note.why ? `<details class="practice-more"><summary>技术原因</summary>
        <p>${escapeHtml(note.why)}</p></details>` : ""}
      ${note.evidence ? `<pre class="practice-evidence">${escapeHtml(note.evidence)}</pre>` : ""}
      <div class="practice-meta">
        ${note.tags ? `<span class="practice-tags">${escapeHtml(note.tags)}</span>` : ""}
        ${project ? `<span>${escapeHtml(project)}</span>` : ""}
        ${source ? `<span>来自${escapeHtml(source)}</span>` : ""}
        ${note.last_used ? `<span>上次用到 ${escapeHtml(String(note.last_used).slice(0, 10))}</span>` : ""}
      </div>
      <div class="practice-actions">
        <button class="btn btn-small" type="button" data-act="used">这次用到了</button>
        <button class="btn btn-small btn-quiet" type="button" data-act="edit">编辑</button>
        <button class="btn btn-small btn-quiet" type="button" data-act="archive">归档</button>
      </div>
    </article>`;
}

function openForm(note, draft) {
  const data = note || draft || {};
  editingId = note ? Number(note.id) : 0;
  nodes.formTitle.textContent = editingId ? "编辑经验" : "记一条经验";
  nodes.title.value = data.title || "";
  nodes.scene.value = data.scene || "";
  nodes.pitfall.value = data.pitfall || "";
  nodes.next.value = data.next_time || data.next || "";
  nodes.why.value = data.why || "";
  nodes.evidence.value = data.evidence || "";
  nodes.tags.value = data.tags || "";
  nodes.formProject.value = String(data.project_id || 0);
  const kind = data.kind === "good_practice" ? "good_practice" : "pitfall";
  for (const radio of document.querySelectorAll('input[name="practice-kind"]')) {
    radio.checked = radio.value === kind;
  }
  nodes.status.textContent = "";
  nodes.formPanel.hidden = false;
  nodes.formPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  nodes.title.focus();
}

function closeForm() {
  nodes.formPanel.hidden = true;
  editingId = 0;
}

function formPayload() {
  const kind = document.querySelector('input[name="practice-kind"]:checked');
  return {
    title: nodes.title.value.trim(),
    scene: nodes.scene.value.trim(),
    pitfall: nodes.pitfall.value.trim(),
    next_time: nodes.next.value.trim(),
    kind: kind ? kind.value : "pitfall",
    why: nodes.why.value.trim(),
    evidence: nodes.evidence.value.trim(),
    tags: nodes.tags.value.trim(),
    project_id: Number(nodes.formProject.value || 0),
  };
}

async function save() {
  const payload = formPayload();
  if (!payload.title || !payload.scene || !payload.pitfall || !payload.next_time) {
    nodes.status.textContent = "标题、场景、坑、下次都要填。";
    return;
  }
  nodes.save.disabled = true;
  nodes.status.textContent = "保存中…";
  try {
    if (editingId) {
      await api.patch(`/api/practice/${editingId}`, payload);
      toast("经验已更新", "ok");
    } else {
      await api.post("/api/practice", payload);
      toast("经验已记下", "ok");
    }
    closeForm();
    await load();
  } catch (error) {
    nodes.status.textContent = error.message || "保存失败";
  } finally {
    nodes.save.disabled = false;
  }
}

async function onListClick(event) {
  const button = event.target.closest("[data-act]");
  const card = event.target.closest(".practice-card");
  if (!button || !card) return;
  const note = items.find((item) => item.id === Number(card.dataset.id));
  if (!note) return;
  const action = button.dataset.act;
  if (action === "edit") {
    openForm(note);
    return;
  }
  button.disabled = true;
  try {
    if (action === "used") {
      const data = await api.post(`/api/practice/${note.id}/used`, {});
      toast(`已记一次：用到 ${data.used_count} 次`, "ok");
      await load();
    } else if (action === "archive") {
      await api.post(`/api/practice/${note.id}/archive`, {});
      toast("已归档", "ok");
      await load();
    }
  } catch (error) {
    button.disabled = false;
    toast(error.message || "操作失败", "err");
  }
}
