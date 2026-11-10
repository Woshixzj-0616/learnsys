// 资料导入层：文件上传、目录批量导入、拖拽投放与新建笔记。
import { api, uploadRaw } from "../api.js";
import { toast } from "../ui.js";

const ACCEPT = /\.(pdf|docx|pptx|txt|md)$/i;
const MAX_BYTES = 50 * 1024 * 1024;

export async function importDirectory(app) {
  const path = prompt(
    "要导入哪个文件夹？\n\n先在设置里把目录加到 materials.import_dirs；不移动原文件。");
  if (!path?.trim()) return;
  const obsidian = confirm("这是 Obsidian 笔记库吗？\n\n确定 = 只导入 .md；取消 = 课程资料（PDF/DOCX/PPTX/TXT/MD）");
  app.nodes.status.textContent = "正在扫描目录…";
  try {
    const result = await api.post("/api/materials/import-dir", {
      path: path.trim(),
      source: obsidian ? "obsidian" : "courses",
    });
    app.nodes.status.textContent =
      `扫描 ${result.scanned} 份：导入 ${result.imported}，已存在跳过 ${result.skipped}，失败 ${result.failed}`;
    toast(`导入完成：新增 ${result.imported} 份`, result.imported ? "ok" : "info");
    const firstFailure = (result.items || [])[0];
    if (firstFailure) {
      toast(`${firstFailure.title}：${firstFailure.why}`, "err");
    }
    await app.loadList();
  } catch (error) {
    app.nodes.status.textContent = "";
    toast(error.message || "这个目录没导进来", "err");
  }
}

async function uploadFiles(app, files) {
  const picked = files.filter((file) => ACCEPT.test(file.name));
  if (!picked.length) {
    toast("只支持 PDF / DOCX / PPTX / TXT / MD", "err");
    return;
  }
  app.nodes.importBtn.disabled = true;
  let done = 0;
  for (const file of picked) {
    app.nodes.status.textContent = `正在导入 ${done + 1}/${picked.length}：${file.name}`;
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
  app.nodes.status.textContent = `本轮导入完成（${done}/${picked.length}）`;
  app.nodes.importBtn.disabled = false;
  await app.loadList();
}

async function createNote(app) {
  const title = window.prompt("笔记标题", "新笔记");
  if (title === null) return;
  try {
    const safeTitle = (title.trim() || "新笔记").slice(0, 200);
    const data = await api.post("/api/materials/note", {
      title: safeTitle, body: "# " + safeTitle + "\n\n",
    });
    toast("笔记已创建", "ok");
    await app.loadList();
    await app.selectMaterial(data.item.id);
  } catch (error) {
    toast(error.message || "新建失败", "err");
  }
}

function bindDrop(app) {
  const nodes = app.nodes;
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
    uploadFiles(app, Array.from(event.dataTransfer.files));
  });
}

export function bindImport(app) {
  const nodes = app.nodes;
  nodes.importBtn.addEventListener("click", () => nodes.file.click());
  nodes.dirImport.addEventListener("click", () => importDirectory(app));
  nodes.file.addEventListener("change", () => {
    const files = Array.from(nodes.file.files || []);
    nodes.file.value = "";
    uploadFiles(app, files);
  });
  nodes.newNote.addEventListener("click", () => createNote(app));
  bindDrop(app);
}
