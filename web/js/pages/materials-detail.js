// 资料详情层：正文 / 笔记编辑、资料操作与「生成术语表 / 提纲」弹窗。
import { api, download, streamChat } from "../api.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, toast } from "../ui.js";
import { KIND_LABEL } from "./materials-list.js";

let genText = "";
let genTitle = "";
let genStreaming = false;
let controller = null;

export function renderDetailEmpty(app) {
  app.nodes.detail.innerHTML = `<div class="empty"><strong>选一份资料</strong>
    左边点一份课件或笔记，这里显示正文与操作。</div>`;
  app.nodes.detailState.textContent = "";
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

export function renderDetail(app) {
  const item = app.selected;
  if (!item) return renderDetailEmpty(app);
  const tags = item.tags ? `<span>标签：${escapeHtml(item.tags)}</span>` : "";
  const meta = `<div class="mat-meta">
    <span>${escapeHtml(KIND_LABEL[item.kind] || item.kind)} · ${escapeHtml(item.chars)} 字${item.pages ? ` · ${item.pages} 页` : ""}</span>
    ${item.course ? `<span>课程：${escapeHtml(item.course)}</span>` : ""}
    ${tags}
    <span>更新：${escapeHtml(String(item.updated_at || "").slice(0, 16))}</span>
  </div>`;
  if (item.kind === "note") {
    app.nodes.detail.innerHTML = `
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
    const textarea = app.nodes.detail.querySelector("#mat-note-body");
    const preview = app.nodes.detail.querySelector("#mat-note-preview");
    const paint = () => renderInto(preview, textarea.value || "（空笔记）");
    textarea.addEventListener("input", paint);
    textarea.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveNote(app);
      }
    });
    app.nodes.detail.querySelector("#mat-note-save").addEventListener("click", () => saveNote(app));
    paint();
    return;
  }
  app.nodes.detail.innerHTML = `
    <div class="mat-detail-head">
      <h3>${escapeHtml(item.title)}</h3>
      ${meta}
      <div class="mat-actions">${matActions(item)}</div>
    </div>
    <div class="mat-body-reader" id="mat-body-reader"></div>`;
  const reader = app.nodes.detail.querySelector("#mat-body-reader");
  const pre = document.createElement("pre");
  pre.className = "mat-body-pre";
  pre.textContent = (item.body || "（没有抽到正文）").replaceAll("\f", "\n\n--- 分页 ---\n\n");
  reader.appendChild(pre);
}

async function saveNote(app) {
  const textarea = app.nodes.detail.querySelector("#mat-note-body");
  if (!app.selected || !textarea) return;
  try {
    const data = await api.post(`/api/materials/${app.selected.id}`, { body: textarea.value });
    app.selected = data.item;
    app.nodes.detail.querySelector("#mat-note-hint").textContent = "已保存";
    toast("笔记已保存", "ok");
    app.loadList();
  } catch (error) {
    toast(error.message || "保存失败", "err");
  }
}

export async function onDetailClick(app, event) {
  const button = event.target.closest("[data-act]");
  if (!button || !app.selected) return;
  const action = button.dataset.act;
  if (action === "open") return openOriginal(app);
  if (action === "ask") return askAbout(app);
  if (action === "quiz") return quizFromMaterial(app);
  if (action === "glossary") return generate(app, "glossary");
  if (action === "outline") return generate(app, "outline");
  if (action === "export") return exportMaterial(app);
  if (action === "trash") return trashMaterial(app);
  if (action === "restore") return restoreMaterial(app);
  if (action === "delete") return deleteMaterial(app);
}

async function openOriginal(app) {
  try {
    await api.post(`/api/materials/${app.selected.id}/open`, {});
    toast("已用系统默认程序打开原文", "ok");
  } catch (error) {
    toast(error.message || "打不开原文", "err");
  }
}

async function exportMaterial(app) {
  try {
    const name = String(app.selected.title || "资料").replace(/\.[^.]+$/, "") || "资料";
    await download(`/api/materials/${app.selected.id}/export`, `${name}.md`);
    toast("已导出 Markdown", "ok");
  } catch (error) {
    toast(error.message || "导出失败", "err");
  }
}

function askAbout(app) {
  const prompt = "先讲清这份资料的整体结构，再指出最该记住的 5 个点。";
  location.hash = `#/ask?material=${app.selected.id}&prompt=${encodeURIComponent(prompt)}`;
}

function quizFromMaterial(app) {
  location.hash = `#/quiz?material=${app.selected.id}`;
}

async function trashMaterial(app) {
  if (!window.confirm("移入回收站？原文和笔记都还能恢复。")) return;
  try {
    await api.post(`/api/materials/${app.selected.id}/trash`, {});
    toast("已移入回收站", "ok");
    app.selected = null;
    renderDetailEmpty(app);
    await app.loadList();
  } catch (error) {
    toast(error.message || "移入回收站失败", "err");
  }
}

async function restoreMaterial(app) {
  try {
    await api.post(`/api/materials/${app.selected.id}/restore`, {});
    toast("已恢复", "ok");
    app.selected = null;
    renderDetailEmpty(app);
    await app.loadList();
  } catch (error) {
    toast(error.message || "恢复失败", "err");
  }
}

async function deleteMaterial(app) {
  if (!window.confirm("彻底删除？原文件和记录都会删掉，不能恢复。")) return;
  try {
    await api.del(`/api/materials/${app.selected.id}`);
    toast("已彻底删除", "ok");
    app.selected = null;
    renderDetailEmpty(app);
    await app.loadList();
  } catch (error) {
    toast(error.message || "删除失败", "err");
  }
}

function generate(app, kindName) {
  if (genStreaming || !app.selected) return;
  const isGlossary = kindName === "glossary";
  genTitle = `${app.selected.title} · ${isGlossary ? "术语表" : "提纲"}`.slice(0, 200);
  genText = "";
  app.nodes.genTitleNode.textContent = genTitle;
  app.nodes.genResult.innerHTML = '<p class="hint">正在读资料并生成…</p>';
  app.nodes.genSave.disabled = true;
  app.nodes.genModal.hidden = false;
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
    material_id: app.selected.id,
  }, (event) => {
    if (event.kind === "text") {
      genText += event.text || "";
      renderInto(app.nodes.genResult, genText);
    } else if (event.kind === "rewrite") {
      genText = String(event.data?.text || genText);
      renderInto(app.nodes.genResult, genText);
    } else if (event.kind === "done") {
      const final = String(event.data?.text || genText || "");
      if (final) {
        genText = final;
        renderInto(app.nodes.genResult, genText);
      }
    } else if (event.kind === "error") {
      app.nodes.genResult.innerHTML = `<p class="review-error">${escapeHtml(event.text || "生成失败")}</p>`;
    }
  }, controller.signal).catch((error) => {
    if (error?.name !== "AbortError") {
      app.nodes.genResult.innerHTML = `<p class="review-error">${escapeHtml(error.message || error)}</p>`;
    }
  }).finally(() => {
    genStreaming = false;
    controller = null;
    app.nodes.genSave.disabled = !genText.trim();
  });
}

function closeGen(app) {
  if (genStreaming) controller?.abort();
  app.nodes.genModal.hidden = true;
}

async function saveGen(app) {
  const body = genText.trim();
  if (!body) return;
  app.nodes.genSave.disabled = true;
  try {
    const data = await api.post("/api/materials/note", {
      title: genTitle,
      body,
      course: (app.selected?.course || "").slice(0, 80),
      tags: "生成",
    });
    toast("已保存为笔记", "ok");
    app.nodes.genModal.hidden = true;
    await app.loadList();
    app.selectMaterial(data.item.id);
  } catch (error) {
    app.nodes.genSave.disabled = false;
    toast(error.message || "保存失败", "err");
  }
}

export function bindDetail(app) {
  const nodes = app.nodes;
  nodes.detail.addEventListener("click", (event) => onDetailClick(app, event));
  nodes.genClose.addEventListener("click", () => closeGen(app));
  nodes.genSave.addEventListener("click", () => saveGen(app));
  nodes.genModal.addEventListener("click", (event) => {
    if (event.target === nodes.genModal) closeGen(app);
  });
}

export function abortGeneration() {
  if (genStreaming) controller?.abort();
}
