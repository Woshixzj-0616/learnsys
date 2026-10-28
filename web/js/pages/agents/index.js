// Agent 中枢：只读派活页。入口 #/agents。
import { api } from "../../api.js";
import { toast } from "../../ui.js";
import { createCompose } from "./compose.js";
import { createLog } from "./log.js";
import { renderHistory } from "./history.js";

let nodes = {};
let meta = { agents: [], allowed_roots: [], default_workspace: "", timeout: 300 };
let tasks = [];
let compose = null;
let log = null;

function updateStats() {
  const chips = nodes.stats?.querySelectorAll("strong");
  if (!chips || chips.length < 3) return;
  chips[0].textContent = String(meta.agents.filter((item) => item.available).length);
  chips[1].textContent = String(tasks.filter(
    (item) => item.status === "running" || item.status === "queued").length);
  chips[2].textContent = String(tasks.length);
}

function renderList() {
  renderHistory({
    root: nodes.root,
    tasks,
    agents: meta.agents,
    onOpen: (task) => log.open(task),
  });
}

async function loadTasks() {
  const data = await api.get("/api/agents/tasks?limit=20");
  tasks = data?.tasks || [];
  renderList();
  updateStats();
}

async function loadMeta() {
  meta = await api.get("/api/agents");
  await compose.load(meta);
  updateStats();
}

async function startTask(body) {
  const data = await api.post("/api/agents/tasks", body);
  const task = data?.task;
  if (!task) throw new Error("后台没有返回任务");
  toast(`任务 #${task.id} 已启动`);
  await loadTasks();
  await log.open(task);
}

async function stopTask(taskId) {
  await api.post(`/api/agents/tasks/${taskId}/cancel`, {});
  await loadTasks();
}

async function decideApproval(id, decision) {
  await api.post(`/api/agents/approvals/${id}/decide`, { decision });
  toast(decision === "allow" ? "已允许这次操作" : "已拒绝这次操作");
  await log.poll();
}

export async function mount(ctx) {
  nodes = {
    root: ctx.root,
    stats: ctx.root.querySelector("#ag-stats"),
    refresh: ctx.root.querySelector("#ag-refresh"),
  };
  compose = createCompose({ root: ctx.root, onStart: startTask });
  nodes.refresh?.addEventListener("click", async () => {
    try {
      await loadMeta();
      await loadTasks();
      toast("已刷新");
    } catch (error) {
      toast(error?.message || "刷新失败");
    }
  });
  try {
    await loadMeta();
    log = createLog({
      root: ctx.root,
      agents: meta.agents,
      onStop: stopTask,
      onDecide: decideApproval,
      onTerminal: () => { loadTasks().catch(() => {}); },
    });
    await loadTasks();
  } catch (error) {
    nodes.root.querySelector("#ag-list").innerHTML =
      `<div class="empty"><strong>Agent 中枢没读出来</strong>${error?.message || ""}</div>`;
  }
}

export function unmount() {
  log?.close();
}
