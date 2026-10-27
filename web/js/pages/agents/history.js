// 最近任务列表。
import { escapeHtml } from "../../ui.js";
import { agentName, msText, promptPreview, statusText } from "./format.js";

function timeText(value) {
  const text = String(value || "");
  return text.length >= 16 ? text.slice(5, 16) : text;
}

export function renderHistory({ root, tasks, agents, onOpen }) {
  const list = root.querySelector("#ag-list");
  const count = root.querySelector("#ag-count");
  count.textContent = tasks.length ? `${tasks.length} 个` : "";
  if (!tasks.length) {
    list.innerHTML = `<div class="empty"><strong>还没有派过任务</strong>
      在上面写一句话，选 Claude Code 或 Codex 就能开始。</div>`;
    return;
  }
  list.innerHTML = tasks.map((task) => {
    const state = task.status || "queued";
    return `<article class="agents-card">
      <div class="agents-card-top">
        <strong>${escapeHtml(agentName(task.agent, agents))} · 任务 #${task.id}</strong>
        <span class="agents-status ${escapeHtml(state)}">${escapeHtml(statusText(state))}</span>
      </div>
      <div class="agents-card-prompt">${escapeHtml(promptPreview(task.prompt))}</div>
      <div class="agents-card-meta">
        ${escapeHtml(timeText(task.created_at))}
        ${task.duration_ms ? ` · ${escapeHtml(msText(task.duration_ms))}` : ""}
        ${task.workspace ? ` · ${escapeHtml(task.workspace)}` : ""}
      </div>
      <button class="btn" type="button" data-task="${task.id}">查看日志</button>
    </article>`;
  }).join("");
  list.querySelectorAll("[data-task]").forEach((button) => {
    button.addEventListener("click", () => {
      const task = tasks.find((item) => String(item.id) === button.dataset.task);
      if (task) onOpen(task);
    });
  });
}
