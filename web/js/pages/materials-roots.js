// 资料页顶部：显示「本机可读目录」，说明 agent 不必等导入。
import { api } from "../api.js";
import { escapeHtml } from "../ui.js";

export async function loadReadRoots(node) {
  if (!node) return;
  try {
    const settings = await api.get("/api/settings");
    const dirs = Array.isArray(settings.materials?.import_dirs)
      ? settings.materials.import_dirs : [];
    node.innerHTML = dirs.length
      ? `agent 可直接读：${dirs.map((item) => escapeHtml(item)).join("、")}
         · <a href="#/settings">去管理</a>`
      : '还没有本机可读目录；agent 目前只能读已导入的资料 · <a href="#/settings">去工具页添加</a>';
  } catch {
    node.textContent = "";
  }
}
