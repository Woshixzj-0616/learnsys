// 资料库：上传/抽取、检索、笔记编辑、AI 术语表/提纲、回收站。
import { api, download, streamChat, uploadRaw } from "../api.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, toast } from "../ui.js";

const KIND_LABEL = { pdf: "PDF", docx: "Word", pptx: "PPT", txt: "TXT", md: "Markdown", note: "笔记" };
const ACCEPT = /\.(pdf|docx|pptx|txt|md)$/i;
const MAX_BYTES = 50 * 1024 * 1024;

let items = [];
let counts = { active: 0, trashed: 0 };
let status = "active";
let kind = "";
let query = "";
let selected = null;      // 完整资料（含 body）
let genText = "";
let genTitle = "";
let genStreaming = false;
let controller = null;
let nodes = {};

export async function mount(ctx) {
  ctx.setSub("课件、笔记、术语表；导入后能搜、能问、能生成");
  ctx.setActions('<a class="btn" href="#/ask">去问一问</a>');
  nodes = {
    stats: ctx.root.querySelector("#mat-stats"),
    list: ctx.root.querySelector("#mat-list"),
    detail: ctx.root.querySelector("#mat-detail"),
    detailState: ctx.root.querySelector("#mat-detail-state"),
    search: ctx.root.querySelector("#mat-search"),
    kind: ctx.root.querySelector("#mat-kind"),
    trash: ctx.root.querySelector("#mat-trash-toggle"),
    importBtn: ctx.root.querySelector("#mat-import"),
    file: ctx.root.querySelector("#mat-file"),
    status: ctx.root.querySelector("#mat-status"),
    drop: ctx.root.querySelector("#mat-drop"),
    newNote: ctx.root.querySelector("#mat-new-note"),
    genModal: ctx.root.querySelector("#mat-gen-modal"),
    genTitleNode: ctx.root.querySelector("#mat-gen-title"),
    genResult: ctx.root.querySelector("#mat-gen-result"),
    genSave: ctx.root.querySelector("#mat-gen-save"),
    genClose: ctx.root.querySelector("#mat-gen-close"),
  };
  bind();
  await loadList();
}

export function unmount() {
  controller?.abort();
}

function bind() {
  nodes.importBtn.addEventListener("click", () => nodes.file.click());
  nodes.file.addEventListener("change", () => {
    const files = Array.from(nodes.file.files || []);
    nodes.file.value = "";
    uploadFiles(files);
  });
  nodes.newNote.addEventListener("click", createNote);
  nodes.search.addEventListener("input", () => {
    clearTimeout(nodes.search._timer);
    nodes.search._timer = setTimeout(() => {
      query = nodes.search.value.trim();
      loadList();
    }, 220);
  });
  nodes.kind.addEventListener("change", () => {
    kind = nodes.kind.value;
    loadList();
  });
  nodes.trash.addEventListener("click", () => {
    status = status === "active" ? "trashed" : "active";
    nodes.trash.classList.toggle("active", status === "trashed");
    nodes.trash.textContent = status === "active" ? "回收站" : "返回资料";
    selected = null;
    renderDetailEmpty();
    loadList();
  });
  nodes.list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-material]");
    if (!button) return;
    selectMaterial(Number(button.dataset.material));
  });
  nodes.detail.addEventListener("click", onDetailClick);
  nodes.genClose.addEventListener("click", closeGen);
  nodes.genSave.addEventListener("click", saveGen);
  nodes.genModal.addEventListener("click", (event) => {
    if (event.target === nodes.genModal) closeGen();
  });
  bindDrop();
}

function bindDrop() {
  const page = nodes.drop.parentElement;
  let depth = 0;
  page.addEventListener("dragenter", (event) => {
    if (!event.dataTransfer?.types?.includes("Files")) return;
    event.preventDefault();
    depth += 1;
    nodes.drop.hidden = false;
  });
  page.addEventListener("dragover", (event) => {
    if (event.dataTransfer?.types?.includes("Files")) event.preventDefault();
  });
  page.addEventListener("dragleave", () => {
    depth = Math.max(0, depth - 1);
    if (!depth) nodes.drop.hidden = true;
  });
  page.addEventListener("drop", (event) => {
    if (!event.dataTransfer?.files?.length) return;
    event.preventDefault();
    depth = 0;
    nodes.drop.hidden = true;
    uploadFiles(Array.from(event.dataTransfer.files));
  });
}

async function loadList() {
  nodes.list.innerHTML = '<div class="empty">正在读资料库…</div>';
  try {
    const params = new URLSearchParams({ status, limit: "200" });
    if (kind) params.set("kind", kind);
    if (query) params.set("q", query);
    const data = await api.get(`/api/materials?${params}`);
    items = Array.isArray(data.items) ? data.items : [];
    counts = data.counts || counts;
    renderStats();
    renderList();
  } catch (error) {
    nodes.list.innerHTML = `<div class="empty"><strong>资料库没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function renderStats() {
  nodes.stats.innerHTML = [
    ["资料", counts.active ?? 0],
    ["回收站", counts.trashed ?? 0],
    ["当前结果", items.length],
  ].map(([label, value]) => `
    <div class="review-chip"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
}

function renderList() {
  if (!items.length) {
    nodes.list.innerHTML = `<div class="empty"><strong>${status === "trashed" ? "回收站是空的" : "还没有资料"}</strong>
      ${status === "trashed" ? "删掉的资料会先来这儿。" : "点右上角「导入资料」，或把 PDF / PPT 拖进来。"}</div>`;
    return;
  }
  nodes.list.innerHTML = items.map((item) => `
    <button class="mat-item ${selected?.id === item.id ? "active" : ""}" type="button"
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

async function selectMaterial(id) {
  nodes.detailState.textContent = "正在读…";
  try {
    const data = await api.get(`/api/materials/${id}?body=1`);
    selected = data.item;
    renderList();
    renderDetail();
    nodes.detailState.textContent = "";
  } catch (error) {
    nodes.detailState.textContent = "";
    toast(error.message || "资料没读出来", "err");
  }
}

function renderDetailEmpty() {
  nodes.detail.innerHTML = `<div class="empty"><strong>选一份资料</strong>
    左边点一份课件或笔记，这里显示正文与操作。</div>`;
  nodes.detailState.textContent = "";
}

function matActions(item) {
  const actions = [];
  if (item.kind !== "note" && item.path) {
    actions.push('<button class="btn" type="button" data-act="open">打开原文</button>');
  }
  if (item.status === "active") {
    actions.push('<button class="btn" type="button" data-act="ask">问这份资料</button>');
    actions.push('<button class="btn" type="button" data-act="quiz">用这份资料出题</button>');
    actions.push('<button class="btn" type="button" data-act="glossary">生成术语表</button>');
    actions.push('<button class="btn" type="button" data-act="outline">生成提纲</button>');
    actions.push('<button class="btn btn-quiet" type="button" data-act="export">导出 MD</button>');
    actions.push('<button class="btn btn-danger" type="button" data-act="trash">移入回收站</button>');
  } else {
    actions.push('<button class="btn btn-primary" type="button" data-act="restore">恢复</button>');
    actions.push('<button class="btn btn-danger" type="button" data-act="delete">彻底删除</button>');
  }
  return actions.join("");
}

function renderDetail() {
  const item = selected;
  if (!item) return renderDetailEmpty();
  const tags = item.tags ? `<span>标签：${escapeHtml(item.tags)}</span>` : "";
  const meta = `<div class="mat-meta">
    <span>${escapeHtml(KIND_LABEL[item.kind] || item.kind)} · ${escapeHtml(item.chars)} 字${item.pages ? ` · ${item.pages} 页` : ""}</span>
    ${item.course ? `<span>课程：${escapeHtml(item.course)}</span>` : ""}
    ${tags}
    <span>更新：${escapeHtml(String(item.updated_at || "").slice(0, 16))}</span>
  </div>`;
  if (item.kind === "note") {
    nodes.detail.innerHTML = `
      <div class="mat-detail-head">
        <h3>${escapeHtml(item.title)}</h3>
        ${meta}
        <div class="mat-actions">${matActions(item)}</div>
      </div>
      <div class="mat-note-editor">
        <textarea id="mat-note-body" spellcheck="false">${escapeHtml(item.body || "")}</textarea>
        <div class="mat-note-actions">
          <button class="btn btn-primary" type="button" id="mat-note-save">保存笔记</button>
          <span class="hint" id="mat-note-hint">Ctrl+S 也能保存</span>
        </div>
        <div class="mat-note-preview" id="mat-note-preview"></div>
      </div>`;
    const textarea = nodes.detail.querySelector("#mat-note-body");
    const preview = nodes.detail.querySelector("#mat-note-preview");
    const paint = () => renderInto(preview, textarea.value || "（空笔记）");
    textarea.addEventListener("input", paint);
    textarea.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveNote();
      }
    });
    nodes.detail.querySelector("#mat-note-save").addEventListener("click", saveNote);
    paint();
    return;
  }
  nodes.detail.innerHTML = `
    <div class="mat-detail-head">
      <h3>${escapeHtml(item.title)}</h3>
      ${meta}
      <div class="mat-actions">${matActions(item)}</div>
    </div>
    <div class="mat-body-reader" id="mat-body-reader"></div>`;
  const reader = nodes.detail.querySelector("#mat-body-reader");
  const pre = document.createElement("pre");
  pre.className = "mat-body-pre";
  pre.textContent = (item.body || "（没有抽到正文）").replaceAll("\f", "\n\n--- 分页 ---\n\n");
  reader.appendChild(pre);
}

async function saveNote() {
  const textarea = nodes.detail.querySelector("#mat-note-body");
  if (!selected || !textarea) return;
  try {
    const data = await api.post(`/api/materials/${selected.id}`, { body: textarea.value });
    selected = data.item;
    nodes.detail.querySelector("#mat-note-hint").textContent = "已保存";
    toast("笔记已保存", "ok");
    loadList();
  } catch (error) {
    toast(error.message || "保存失败", "err");
  }
}

async function onDetailClick(event) {
  const button = event.target.closest("[data-act]");
  if (!button || !selected) return;
  const action = button.dataset.act;
  if (action === "open") return openOriginal();
  if (action === "ask") return askAbout();
  if (action === "quiz") return quizFromMaterial();
  if (action === "glossary") return generate("glossary");
  if (action === "outline") return generate("outline");
  if (action === "export") return exportMaterial();
  if (action === "trash") return trashMaterial();
  if (action === "restore") return restoreMaterial();
  if (action === "delete") return deleteMaterial();
}

async function openOriginal() {
  try {
    await api.post(`/api/materials/${selected.id}/open`, {});
    toast("已用系统默认程序打开原文", "ok");
  } catch (error) {
    toast(error.message || "打不开原文", "err");
  }
}

async function exportMaterial() {
  try {
    const name = String(selected.title || "资料").replace(/\.[^.]+$/, "") || "资料";
    await download(`/api/materials/${selected.id}/export`, `${name}.md`);
    toast("已导出 Markdown", "ok");
  } catch (error) {
    toast(error.message || "导出失败", "err");
  }
}

function askAbout() {
  const prompt = "先讲清这份资料的整体结构，再指出最该记住的 5 个点。";
  location.hash = `#/ask?material=${selected.id}&prompt=${encodeURIComponent(prompt)}`;
}

function quizFromMaterial() {
  location.hash = `#/quiz?material=${selected.id}`;
}

async function trashMaterial() {
  if (!window.confirm("移入回收站？原文和笔记都还能恢复。")) return;
  try {
    await api.post(`/api/materials/${selected.id}/trash`, {});
    toast("已移入回收站", "ok");
    selected = null;
    renderDetailEmpty();
    await loadList();
  } catch (error) {
    toast(error.message || "移入回收站失败", "err");
  }
}

async function restoreMaterial() {
  try {
    await api.post(`/api/materials/${selected.id}/restore`, {});
    toast("已恢复", "ok");
    selected = null;
    renderDetailEmpty();
    await loadList();
  } catch (error) {
    toast(error.message || "恢复失败", "err");
  }
}

async function deleteMaterial() {
  if (!window.confirm("彻底删除？原文件和记录都会删掉，不能恢复。")) return;
  try {
    await api.del(`/api/materials/${selected.id}`);
    toast("已彻底删除", "ok");
    selected = null;
    renderDetailEmpty();
    await loadList();
  } catch (error) {
    toast(error.message || "删除失败", "err");
  }
}

async function createNote() {
  const title = window.prompt("笔记标题", "新笔记");
  if (title === null) return;
  try {
    const safeTitle = (title.trim() || "新笔记").slice(0, 200);
    const data = await api.post("/api/materials/note", {
      title: safeTitle, body: "# " + safeTitle + "\n\n",
    });
    toast("笔记已创建", "ok");
    await loadList();
    await selectMaterial(data.item.id);
  } catch (error) {
    toast(error.message || "新建失败", "err");
  }
}

async function uploadFiles(files) {
  const picked = files.filter((file) => ACCEPT.test(file.name));
  if (!picked.length) {
    toast("只支持 PDF / DOCX / PPTX / TXT / MD", "err");
    return;
  }
  nodes.importBtn.disabled = true;
  let done = 0;
  for (const file of picked) {
    nodes.status.textContent = `正在导入 ${done + 1}/${picked.length}：${file.name}`;
    if (file.size > MAX_BYTES) {
      toast(`${file.name} 超过 50MB，跳过`, "err");
      done += 1;
      continue;
    }
    const params = new URLSearchParams({ name: file.name });
    try {
      const result = await uploadRaw(`/api/materials/upload?${params}`, file);
      done += 1;
      toast(result.created ? `已导入：${file.name}` : `已在资料库：${file.name}`,
            result.created ? "ok" : "");
    } catch (error) {
      done += 1;
      toast(`${file.name}：${error.message || "导入失败"}`, "err");
    }
  }
  nodes.status.textContent = `本轮导入完成（${done}/${picked.length}）`;
  nodes.importBtn.disabled = false;
  await loadList();
}

function generate(kindName) {
  if (genStreaming || !selected) return;
  const isGlossary = kindName === "glossary";
  genTitle = `${selected.title} · ${isGlossary ? "术语表" : "提纲"}`.slice(0, 200);
  genText = "";
  nodes.genTitleNode.textContent = genTitle;
  nodes.genResult.innerHTML = '<p class="hint">正在读资料并生成…</p>';
  nodes.genSave.disabled = true;
  nodes.genModal.hidden = false;
  genStreaming = true;
  controller = new AbortController();
  const prompt = isGlossary
    ? "请从这份资料中提取学科术语，整理成术语表：每行一条，格式「术语 —— 一句话解释（20 字以内）」；只收学科相关词，按出现顺序排。"
    : "请按章节/知识点为这份资料整理一份复习提纲：用 Markdown 两级列表，保留关键定义、公式和易错点。";
  streamChat({
    message: prompt,
    mode: "explain",
    module: "materials",
    internal: true,
    material_id: selected.id,
  }, (event) => {
    if (event.kind === "text") {
      genText += event.text || "";
      renderInto(nodes.genResult, genText);
    } else if (event.kind === "done") {
      const final = String(event.data?.text || genText || "");
      if (final) {
        genText = final;
        renderInto(nodes.genResult, genText);
      }
    } else if (event.kind === "error") {
      nodes.genResult.innerHTML = `<p class="review-error">${escapeHtml(event.text || "生成失败")}</p>`;
    }
  }, controller.signal).catch((error) => {
    if (error?.name !== "AbortError") {
      nodes.genResult.innerHTML = `<p class="review-error">${escapeHtml(error.message || error)}</p>`;
    }
  }).finally(() => {
    genStreaming = false;
    controller = null;
    nodes.genSave.disabled = !genText.trim();
  });
}

function closeGen() {
  if (genStreaming) controller?.abort();
  nodes.genModal.hidden = true;
}

async function saveGen() {
  const body = genText.trim();
  if (!body) return;
  nodes.genSave.disabled = true;
  try {
    const data = await api.post("/api/materials/note", {
      title: genTitle,
      body,
      course: (selected?.course || "").slice(0, 80),
      tags: "生成",
    });
    toast("已保存为笔记", "ok");
    nodes.genModal.hidden = true;
    await loadList();
    await selectMaterial(data.item.id);
  } catch (error) {
    nodes.genSave.disabled = false;
    toast(error.message || "保存失败", "err");
  }
}
