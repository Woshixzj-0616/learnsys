// 创作库：作品档案 + 风格预设 + 豆包文本导入。图片先上传到工作台数据目录。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

let works = [];
let presets = [];
let editingWork = 0;
let editingPreset = 0;
let pendingImage = "";
let workStatus = "active";
let nodes = {};

export async function mount(ctx) {
  ctx.setSub("作品档案：提示词、风格、模型与本地图片；支持从豆包文本导入");
  nodes = {
    stats: ctx.root.querySelector("#art-stats"),
    tabs: ctx.root.querySelector("#art-tabs"),
    worksPane: ctx.root.querySelector("#art-tab-works"),
    presetsPane: ctx.root.querySelector("#art-tab-presets"),
    filters: ctx.root.querySelector("#art-work-filters"),
    workList: ctx.root.querySelector("#art-work-list"),
    workForm: ctx.root.querySelector("#art-work-form"),
    workFormTitle: ctx.root.querySelector("#art-work-form-title"),
    awTitle: ctx.root.querySelector("#aw-title"),
    awPrompt: ctx.root.querySelector("#aw-prompt"),
    awPreset: ctx.root.querySelector("#aw-preset"),
    awModel: ctx.root.querySelector("#aw-model"),
    awFile: ctx.root.querySelector("#aw-file"),
    awFileName: ctx.root.querySelector("#aw-file-name"),
    awNote: ctx.root.querySelector("#aw-note"),
    awCancel: ctx.root.querySelector("#aw-cancel"),
    presetList: ctx.root.querySelector("#art-preset-list"),
    presetForm: ctx.root.querySelector("#art-preset-form"),
    presetFormTitle: ctx.root.querySelector("#art-preset-form-title"),
    apName: ctx.root.querySelector("#ap-name"),
    apPrompt: ctx.root.querySelector("#ap-prompt"),
    apNegative: ctx.root.querySelector("#ap-negative"),
    apNote: ctx.root.querySelector("#ap-note"),
    apCancel: ctx.root.querySelector("#ap-cancel"),
    importForm: ctx.root.querySelector("#art-import-form"),
    aiText: ctx.root.querySelector("#ai-text"),
    aiCancel: ctx.root.querySelector("#ai-cancel"),
  };
  ctx.root.querySelector("#art-new").addEventListener("click", () => openWorkForm());
  ctx.root.querySelector("#art-import-open").addEventListener("click", openImport);
  nodes.tabs.addEventListener("click", onTabClick);
  nodes.filters.addEventListener("click", onFilterClick);
  nodes.workList.addEventListener("click", onWorkClick);
  nodes.presetList.addEventListener("click", onPresetClick);
  nodes.workForm.addEventListener("submit", onSubmitWork);
  nodes.presetForm.addEventListener("submit", onSubmitPreset);
  nodes.importForm.addEventListener("submit", onSubmitImport);
  nodes.awCancel.addEventListener("click", closeWorkForm);
  nodes.apCancel.addEventListener("click", closePresetForm);
  nodes.aiCancel.addEventListener("click", () => { nodes.importForm.hidden = true; });
  nodes.awFile.addEventListener("change", onFileChange);
  await load();
}

export function unmount() {}

async function load() {
  // 先读风格，再渲染作品：作品卡上的风格徽标依赖 presets 已就绪。
  await loadPresets();
  await loadWorks();
  renderStats();
}

async function loadWorks() {
  try {
    const data = await api.get(`/api/art/works?status=${workStatus}`);
    works = Array.isArray(data.items) ? data.items : [];
    renderWorks();
  } catch (error) {
    nodes.workList.innerHTML = `<div class="empty"><strong>作品没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

async function loadPresets() {
  try {
    const data = await api.get("/api/art/presets");
    presets = Array.isArray(data.items) ? data.items : [];
    renderPresets();
    renderPresetOptions();
  } catch (error) {
    nodes.presetList.innerHTML = `<div class="empty"><strong>风格没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function presetName(id) {
  return (presets.find((item) => item.id === id) || {}).name || "";
}

function renderStats() {
  nodes.stats.innerHTML = [
    ["作品", works.length],
    ["风格", presets.length],
  ].map(([label, value]) => `
    <div class="review-chip"><span>${escapeHtml(label)}</span><strong>${value}</strong></div>
  `).join("");
}

function renderWorks() {
  if (!works.length) {
    nodes.workList.innerHTML = `<div class="empty"><strong>这里还没有作品</strong>
      点「新建作品」记一条；也可以把豆包导出的文本直接粘进来导入。</div>`;
    return;
  }
  nodes.workList.innerHTML = works.map((work) => {
    const thumb = work.file_path
      ? `<img class="art-thumb" src="/media/art/${work.id}/image" alt=""
              loading="lazy" onerror="this.hidden=true">`
      : "";
    const style = presetName(work.preset_id);
    const meta = [work.model, String(work.created_at || "").slice(0, 10)]
      .filter(Boolean).join(" · ");
    const actions = work.status === "active"
      ? `<button class="btn btn-quiet" type="button" data-archive="${work.id}">归档</button>`
      : `<button class="btn btn-quiet" type="button" data-restore="${work.id}">恢复</button>`;
    return `
      <article class="art-card">
        ${thumb}
        <div class="art-card-body">
          <div class="art-card-head">
            <strong>${escapeHtml(work.title)}</strong>
            ${style ? `<span class="art-badge">${escapeHtml(style)}</span>` : ""}
          </div>
          <div class="art-card-meta">${escapeHtml(meta || "未填模型")}</div>
          ${work.prompt ? `<p class="art-card-prompt">${escapeHtml(work.prompt)}</p>` : ""}
          ${work.note ? `<div class="art-card-note">${escapeHtml(work.note)}</div>` : ""}
          <div class="art-card-actions">
            ${actions}
            <button class="btn btn-quiet" type="button" data-edit="${work.id}">编辑</button>
            <button class="btn btn-quiet" type="button" data-del="${work.id}">删除</button>
          </div>
        </div>
      </article>`;
  }).join("");
}

function renderPresets() {
  if (!presets.length) {
    nodes.presetList.innerHTML = `<div class="empty"><strong>还没有风格预设</strong>
      新建一个，之后作品可以直接挂上去；导入时遇到新风格名也会自动建档。</div>`;
    return;
  }
  nodes.presetList.innerHTML = presets.map((preset) => `
    <div class="art-preset" data-preset-id="${preset.id}">
      <div class="art-preset-head">
        <strong>${escapeHtml(preset.name)}</strong>
        ${preset.negative ? `<span class="art-badge">反向：${escapeHtml(preset.negative)}</span>` : ""}
      </div>
      ${preset.prompt ? `<div class="art-preset-prompt">${escapeHtml(preset.prompt)}</div>` : ""}
      ${preset.note ? `<div class="art-hint">${escapeHtml(preset.note)}</div>` : ""}
      <div class="art-preset-actions">
        <button class="btn btn-quiet" type="button" data-pedit="${preset.id}">编辑</button>
        <button class="btn btn-quiet" type="button" data-pdel="${preset.id}">删除</button>
      </div>
    </div>`).join("");
}

function renderPresetOptions(selected) {
  const value = selected !== undefined ? selected
    : (nodes.awPreset.value || "0");
  nodes.awPreset.innerHTML = `<option value="0">不挂风格</option>`
    + presets.map((preset) => `<option value="${preset.id}">${escapeHtml(preset.name)}</option>`)
      .join("");
  nodes.awPreset.value = String(value);
}

function onTabClick(event) {
  const button = event.target.closest("[data-tab]");
  if (!button) return;
  const tab = button.dataset.tab;
  for (const node of nodes.tabs.querySelectorAll(".art-tab")) {
    node.classList.toggle("is-active", node === button);
  }
  nodes.worksPane.hidden = tab !== "works";
  nodes.presetsPane.hidden = tab !== "presets";
}

function onFilterClick(event) {
  const button = event.target.closest("[data-status]");
  if (!button) return;
  workStatus = button.dataset.status;
  for (const node of nodes.filters.querySelectorAll(".art-filter")) {
    node.classList.toggle("is-active", node === button);
  }
  loadWorks();
}

/* --------------------------------------------------------------- 作品表单 */

function openWorkForm(work = null) {
  editingWork = work ? work.id : 0;
  pendingImage = work ? work.file_path || "" : "";
  nodes.workFormTitle.textContent = work ? "编辑作品" : "新建作品";
  nodes.awTitle.value = work ? work.title : "";
  nodes.awPrompt.value = work ? work.prompt : "";
  nodes.awModel.value = work ? work.model : "";
  nodes.awNote.value = work ? work.note : "";
  nodes.awFileName.textContent = pendingImage ? "已有图片" : "";
  nodes.awFile.value = "";
  renderPresetOptions(work ? work.preset_id : 0);
  nodes.workForm.hidden = false;
  nodes.awTitle.focus();
}

function closeWorkForm() {
  nodes.workForm.hidden = true;
  editingWork = 0;
  pendingImage = "";
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
}

async function onFileChange() {
  const file = nodes.awFile.files && nodes.awFile.files[0];
  if (!file) return;
  nodes.awFileName.textContent = "上传中…";
  try {
    const data = await readAsDataUrl(file);
    const result = await api.post("/api/upload",
      { name: file.name, data: String(data), kind: "image" });
    pendingImage = result.path || "";
    nodes.awFileName.textContent = `已上传：${file.name}`;
  } catch (error) {
    pendingImage = "";
    nodes.awFileName.textContent = "";
    toast(error.message || error, "err");
  }
}

async function onSubmitWork(event) {
  event.preventDefault();
  const payload = {
    title: nodes.awTitle.value.trim(),
    prompt: nodes.awPrompt.value.trim(),
    preset_id: Number(nodes.awPreset.value || 0),
    model: nodes.awModel.value.trim(),
    file_path: pendingImage,
    note: nodes.awNote.value.trim(),
  };
  if (!payload.title) {
    toast("作品标题不能为空", "err");
    return;
  }
  try {
    if (editingWork) await api.patch(`/api/art/works/${editingWork}`, payload);
    else await api.post("/api/art/works", payload);
    toast("已保存");
    closeWorkForm();
    await load();
  } catch (error) {
    toast(error.message || error, "err");
  }
}

/* --------------------------------------------------------------- 风格表单 */

function openPresetForm(preset = null) {
  editingPreset = preset ? preset.id : 0;
  nodes.presetFormTitle.textContent = preset ? "编辑风格" : "新建风格";
  nodes.apName.value = preset ? preset.name : "";
  nodes.apPrompt.value = preset ? preset.prompt : "";
  nodes.apNegative.value = preset ? preset.negative : "";
  nodes.apNote.value = preset ? preset.note : "";
  nodes.presetForm.hidden = false;
  nodes.apName.focus();
}

function closePresetForm() {
  nodes.presetForm.hidden = true;
  editingPreset = 0;
}

async function onSubmitPreset(event) {
  event.preventDefault();
  const payload = {
    name: nodes.apName.value.trim(),
    prompt: nodes.apPrompt.value.trim(),
    negative: nodes.apNegative.value.trim(),
    note: nodes.apNote.value.trim(),
  };
  if (!payload.name) {
    toast("风格名称不能为空", "err");
    return;
  }
  try {
    if (editingPreset) await api.patch(`/api/art/presets/${editingPreset}`, payload);
    else await api.post("/api/art/presets", payload);
    toast("已保存");
    closePresetForm();
    await load();
  } catch (error) {
    toast(error.message || error, "err");
  }
}

/* ----------------------------------------------------------------- 导入 */

function openImport() {
  nodes.importForm.hidden = false;
  nodes.aiText.focus();
}

async function onSubmitImport(event) {
  event.preventDefault();
  const text = nodes.aiText.value.trim();
  if (!text) {
    toast("先粘贴要导入的文本", "err");
    return;
  }
  try {
    const result = await api.post("/api/art/import", { text });
    toast(`已导入 ${Number(result.count || 0)} 件`);
    nodes.aiText.value = "";
    nodes.importForm.hidden = true;
    await load();
  } catch (error) {
    toast(error.message || error, "err");
  }
}

/* --------------------------------------------------------------- 列表动作 */

async function act(path) {
  try {
    await api.post(path);
    await load();
  } catch (error) {
    toast(error.message || error, "err");
  }
}

function onWorkClick(event) {
  const archive = event.target.closest("[data-archive]");
  if (archive) return act(`/api/art/works/${archive.dataset.archive}/archive`);
  const restore = event.target.closest("[data-restore]");
  if (restore) return act(`/api/art/works/${restore.dataset.restore}/restore`);
  const edit = event.target.closest("[data-edit]");
  if (edit) {
    const work = works.find((row) => String(row.id) === edit.dataset.edit);
    if (work) openWorkForm(work);
    return;
  }
  const del = event.target.closest("[data-del]");
  if (del) {
    const work = works.find((row) => String(row.id) === del.dataset.del);
    if (!work) return;
    if (!confirm(`删除作品「${work.title}」？图片文件不会删。`)) return;
    api.del(`/api/art/works/${work.id}`)
      .then(() => { toast("已删除"); return load(); })
      .catch((error) => toast(error.message || error, "err"));
  }
}

function onPresetClick(event) {
  const edit = event.target.closest("[data-pedit]");
  if (edit) {
    const preset = presets.find((row) => String(row.id) === edit.dataset.pedit);
    if (preset) openPresetForm(preset);
    return;
  }
  const del = event.target.closest("[data-pdel]");
  if (del) {
    const preset = presets.find((row) => String(row.id) === del.dataset.pdel);
    if (!preset) return;
    if (!confirm(`删除风格「${preset.name}」？作品会保留，只是不再挂这个风格。`)) return;
    api.del(`/api/art/presets/${preset.id}`)
      .then(() => { toast("已删除"); return load(); })
      .catch((error) => toast(error.message || error, "err"));
  }
}
