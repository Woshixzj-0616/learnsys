// 最近任务列表。
import { escapeHtml } from "../../ui.js";
import { agentName, chainText, modeText, msText, promptPreview,
         statusLabel } from "./format.js";

function timeText(value) {
  const text = String(value || "");
  return text.length >= 16 ? text.slice(5, 16) : text;
}

export function renderHistory({ root, tasks, agents, onOpen, onContinue }) {
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
    const stateLabel = statusLabel(task);
    const chain = chainText(task);
    const canContinue = state !== "failed" && state !== "cancelled"
      && !(state === "done" && !task.has_result);
    const route = task.route || {};
    const suggestion = route.recommended && route.recommended !== route.chosen
      ? `<span class="agents-route-badge" title="${escapeHtml(route.reason || "")}">
           建议 ${escapeHtml(agentName(route.recommended, agents))}</span>`
      : "";
    return `<article class="agents-card">
      <div class="agents-card-top">
        <strong>${escapeHtml(agentName(task.agent, agents))} · 任务 #${task.id}</strong>
        <span class="agents-card-badges">
          <span class="agents-mode ${task.mode === "write" ? "write" : "read"}">
            ${escapeHtml(modeText(task.mode))}</span>
          ${suggestion}
          <span class="agents-status ${escapeHtml(state)}">${escapeHtml(stateLabel)}</span>
        </span>
      </div>
      <div class="agents-card-prompt">${escapeHtml(promptPreview(task.prompt))}</div>
      <div class="agents-card-meta">
        ${escapeHtml(timeText(task.created_at))}
        ${task.duration_ms ? ` · ${escapeHtml(msText(task.duration_ms))}` : ""}
        ${chain ? ` · ${escapeHtml(chain)}` : ""}
        ${task.workspace ? ` · ${escapeHtml(task.workspace)}` : ""}
      </div>
      <div class="agents-card-actions">
        <button class="btn" type="button" data-task="${task.id}">查看日志</button>
        ${canContinue ? `<button class="btn" type="button"
            data-continue="${task.id}">接在此任务之后</button>` : ""}
      </div>
    </article>`;
  }).join("");
  list.querySelectorAll("[data-task]").forEach((button) => {
    button.addEventListener("click", () => {
      const task = tasks.find((item) => String(item.id) === button.dataset.task);
      if (task) onOpen(task);
    });
  });
  list.querySelectorAll("[data-continue]").forEach((button) => {
    button.addEventListener("click", () => {
      const task = tasks.find((item) => String(item.id) === button.dataset.continue);
      if (task) onContinue?.(task);
    });
  });
}
