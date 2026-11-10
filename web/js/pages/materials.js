// 资料库：上传/抽取、检索、笔记编辑、AI 术语表/提纲、回收站。
// 三层拆分：列表 materials-list.js、详情 materials-detail.js、导入 materials-import.js；
// 本机可读目录仍在 materials-roots.js，这里只做装配与选中态。
import { api } from "../api.js";
import { toast } from "../ui.js";
import { loadReadRoots } from "./materials-roots.js";
import { bindList, loadList, renderList } from "./materials-list.js";
import {
  abortGeneration, bindDetail, renderDetail, renderDetailEmpty,
} from "./materials-detail.js";
import { bindImport } from "./materials-import.js";

const app = {
  nodes: {},
  items: [],
  counts: { active: 0, trashed: 0 },
  status: "active",
  kind: "",
  query: "",
  selected: null,
};

async function selectMaterial(id) {
  app.nodes.detailState.textContent = "正在读…";
  try {
    const data = await api.get(`/api/materials/${id}?body=1`);
    app.selected = data.item;
    renderList(app);
    renderDetail(app);
    app.nodes.detailState.textContent = "";
  } catch (error) {
    app.nodes.detailState.textContent = "";
    toast(error.message || "资料没读出来", "err");
  }
}

app.loadList = () => loadList(app);
app.renderDetailEmpty = () => renderDetailEmpty(app);
app.selectMaterial = selectMaterial;

export async function mount(ctx) {
  ctx.setSub("课件、笔记、术语表；本机目录可直接问，导入用于精读与批注");
  ctx.setActions('<a class="btn" href="#/ask">去问一问</a>');
  app.nodes = {
    stats: ctx.root.querySelector("#mat-stats"),
    list: ctx.root.querySelector("#mat-list"),
    detail: ctx.root.querySelector("#mat-detail"),
    detailState: ctx.root.querySelector("#mat-detail-state"),
    search: ctx.root.querySelector("#mat-search"),
    kind: ctx.root.querySelector("#mat-kind"),
    trash: ctx.root.querySelector("#mat-trash-toggle"),
    importBtn: ctx.root.querySelector("#mat-import"),
    dirImport: ctx.root.querySelector("#mat-import-dir"),
    file: ctx.root.querySelector("#mat-file"),
    status: ctx.root.querySelector("#mat-status"),
    drop: ctx.root.querySelector("#mat-drop"),
    newNote: ctx.root.querySelector("#mat-new-note"),
    genModal: ctx.root.querySelector("#mat-gen-modal"),
    genTitleNode: ctx.root.querySelector("#mat-gen-title"),
    genResult: ctx.root.querySelector("#mat-gen-result"),
    genSave: ctx.root.querySelector("#mat-gen-save"),
    genClose: ctx.root.querySelector("#mat-gen-close"),
    readRoots: ctx.root.querySelector("#mat-read-roots"),
  };
  bindList(app);
  bindDetail(app);
  bindImport(app);
  await Promise.all([loadList(app), loadReadRoots(app.nodes.readRoots)]);
}

export function unmount() {
  abortGeneration();
}
