// 任务日志：800ms 轮询增量事件与写操作审批，结束自动停。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";
import { msText, queueText, routeText, statusText, taskTitle } from "./format.js";

const TERMINAL = new Set(["done", "failed", "cancelled"]);
const MAX_LINES = 2000;
const APPROVAL_TEXT = {
  pending: "待确认",
  allowed: "已允许",
  denied: "已拒绝",
  expired: "已超时",
};

export function createLog({ root, agents, onStop, onTerminal, onDecide }) {
  const panel = root.querySelector("#ag-run");
  const title = root.querySelector("#ag-run-title");
  const status = root.querySelector("#ag-status");
  const routeBox = root.querySelector("#ag-route");
  const log = root.querySelector("#ag-log");
  const result = root.querySelector("#ag-result");
  const approvalsBox = root.querySelector("#ag-approvals");
  const stopBtn = root.querySelector("#ag-stop");
  const clearBtn = root.querySelector("#ag-clear");

  let taskId = 0;
  let next = 0;
  let timer = null;
  let terminal = false;
  let notified = false;
  let lines = [];
  let approvals = [];
  let approvalSig = "";

  function render() {
    log.innerHTML = lines.map((line) => {
      const cls = `ag-line ${line.kind}`;
      return `<span class="${cls}">${escapeHtml(line.text)}</span>`;
    }).join("\n");
    const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
    if (nearBottom) log.scrollTop = log.scrollHeight;
  }

  function append(event) {
    const text = String(event.text || "");
    if (!text) return;
    const prefix = event.kind === "tool" ? "▸ "
      : event.kind === "error" ? "✗ "
        : event.kind === "status" ? "· " : "";
    lines.push({ kind: event.kind, text: prefix + text });
    if (lines.length > MAX_LINES) lines = lines.slice(-MAX_LINES);
    render();
  }

  async function decide(id, decision, button) {
    if (!onDecide) return;
    button.disabled = true;
    try {
      await onDecide(id, decision);
    } catch (error) {
      toast(error?.message || "审批没发出去");
      button.disabled = false;
    }
  }

  function renderApprovals() {
    const sig = approvals.map((item) => `${item.id}:${item.status}`).join(",");
    if (sig === approvalSig) return;
    approvalSig = sig;
    if (!approvals.length) {
      approvalsBox.hidden = true;
      approvalsBox.innerHTML = "";
      return;
    }
    approvalsBox.hidden = false;
    approvalsBox.innerHTML = approvals.map((item) => {
      const state = item.status || "pending";
      const pending = state === "pending";
      const preview = item.preview
        ? `<pre class="agents-approval-preview">${escapeHtml(item.preview)}</pre>`
        : "";
      const actions = pending
        ? `<div class="agents-approval-actions">
             <button class="btn btn-primary" type="button"
                     data-approve="${item.id}">允许</button>
             <button class="btn" type="button"
                     data-deny="${item.id}">拒绝</button>
           </div>`
        : `<div class="agents-approval-result">
             ${escapeHtml(APPROVAL_TEXT[state] || state)}
             ${item.reason ? ` · ${escapeHtml(item.reason)}` : ""}
           </div>`;
      return `<article class="agents-approval ${escapeHtml(state)}">
        <div class="agents-approval-head">
          <strong>${escapeHtml(item.summary || item.tool || "操作")}</strong>
          <span class="agents-approval-state">
            ${escapeHtml(APPROVAL_TEXT[state] || state)}</span>
        </div>
        ${preview}
        ${actions}
      </article>`;
    }).join("");
    approvalsBox.querySelectorAll("[data-approve]").forEach((button) => {
      button.addEventListener("click", () => decide(
        Number(button.dataset.approve), "allow", button));
    });
    approvalsBox.querySelectorAll("[data-deny]").forEach((button) => {
      button.addEventListener("click", () => decide(
        Number(button.dataset.deny), "deny", button));
    });
  }

  function renderTask(task) {
    if (!task) return;
    title.textContent = taskTitle(task, agents);
    const state = task.status || "queued";
    status.textContent = state === "queued" ? queueText(task) : statusText(state);
    status.className = `agents-status ${state}`;
    terminal = TERMINAL.has(state);
    stopBtn.hidden = terminal;
    const routeHint = routeText(task.route, agents);
    routeBox.hidden = !routeHint;
    routeBox.textContent = routeHint;
    if (task.output_path) {
      result.hidden = false;
      result.innerHTML = `<strong>结果已存</strong>`
        + `<span>${escapeHtml(task.output_path)}</span>`
        + (task.duration_ms ? `<span>${msText(task.duration_ms)}</span>` : "")
        + (task.cost_usd ? `<span>CLI 自报 $${Number(task.cost_usd).toFixed(4)}</span>` : "");
    } else {
      result.hidden = true;
    }
    if (terminal && timer) {
      clearInterval(timer);
      timer = null;
    }
    if (terminal && !notified) {
      notified = true;
      onTerminal?.(task);
    }
  }

  async function poll() {
    const wanted = taskId;
    if (!wanted) return;
    try {
      const [data, approvalData] = await Promise.all([
        api.get(`/api/agents/tasks/${wanted}/events?after=${next}&limit=1000`),
        api.get(`/api/agents/tasks/${wanted}/approvals?after=0&limit=200`),
      ]);
      if (wanted !== taskId) return;
      for (const event of data.events || []) {
        next = Math.max(next, Number(event.seq) || 0);
        append(event);
      }
      approvals = approvalData.approvals || [];
      renderApprovals();
      renderTask(data.task || approvalData.task);
    } catch (error) {
      if (timer) clearInterval(timer);
      timer = null;
      status.textContent = "读取失败";
      status.className = "agents-status failed";
      append({ kind: "error", text: error?.message || "事件读取失败" });
    }
  }

  async function open(task) {
    if (!task) return;
    taskId = Number(task.id) || 0;
    next = 0;
    lines = [];
    approvals = [];
    approvalSig = "";
    terminal = false;
    notified = false;
    panel.hidden = false;
    log.textContent = "";
    result.hidden = true;
    approvalsBox.hidden = true;
    approvalsBox.innerHTML = "";
    renderTask(task);
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    if (timer) clearInterval(timer);
    timer = setInterval(poll, 800);
    await poll();
  }

  function close() {
    if (timer) clearInterval(timer);
    timer = null;
    taskId = 0;
    panel.hidden = true;
  }

  stopBtn.addEventListener("click", async () => {
    if (!taskId) return;
    stopBtn.disabled = true;
    try {
      await onStop(taskId);
      toast("已请求停止，等进程退出…");
    } catch (error) {
      toast(error?.message || "停止失败");
    } finally {
      stopBtn.disabled = false;
    }
  });
  clearBtn.addEventListener("click", close);

  return { open, close, poll };
}
