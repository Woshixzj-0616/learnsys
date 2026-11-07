// 全局任务条：有派活在跑/排队时，底部中间浮一条；点开进 Agent 中枢。
// 只在有活动任务时出现，不占页面；收起后等任务状态变化再出现。
import { api } from "./api.js";
import { escapeHtml } from "./ui.js";

const POLL_MS = 8000;
let node = null;
let timer = null;
let dismissed = false;
let signature = "";

function shorten(text, size = 30) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value.length > size ? `${value.slice(0, size)}…` : value;
}

function ensureNode() {
  if (node) return node;
  node = document.createElement("div");
  node.className = "agent-bar";
  node.hidden = true;
  node.addEventListener("click", (event) => {
    if (event.target.closest("[data-agent-bar-close]")) {
      dismissed = true;
      node.hidden = true;
      return;
    }
    location.hash = "#/agents";
  });
  document.body.appendChild(node);
  return node;
}

function render(tasks) {
  const box = ensureNode();
  const active = (tasks || []).filter(
    (task) => task.status === "running" || task.status === "queued");
  const sig = active.map((task) => `${task.id}:${task.status}`).join(",");
  if (!active.length) {
    dismissed = false;
    signature = "";
    box.hidden = true;
    return;
  }
  if (dismissed && sig === signature) {
    box.hidden = true;
    return;
  }
  dismissed = false;
  signature = sig;
  const running = active.filter((task) => task.status === "running").length;
  const queued = active.length - running;
  const first = active[0];
  box.hidden = false;
  box.innerHTML = `<span class="agent-bar-dot" aria-hidden="true"></span>
    <span class="agent-bar-text">${running} 运行中${queued ? ` · ${queued} 排队` : ""}`
    + ` · ${escapeHtml(shorten(first.prompt))}</span>
    <button class="agent-bar-close" type="button" data-agent-bar-close
            title="收起，任务状态变化时再出现">×</button>`;
}

async function poll() {
  if (document.hidden) return;
  try {
    const data = await api.get("/api/agents/tasks?limit=20");
    render(data.tasks);
  } catch {
    // 后台没起来时不打扰；壳层已有离线提示
  }
}

export function installAgentBar() {
  if (timer) return;
  ensureNode();
  poll();
  timer = setInterval(poll, POLL_MS);
}
