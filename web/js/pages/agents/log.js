// 任务日志：800ms 轮询增量事件，按 kind 着色，结束自动停。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";
import { msText, statusText, taskTitle } from "./format.js";

const TERMINAL = new Set(["done", "failed", "cancelled"]);
const MAX_LINES = 2000;

export function createLog({ root, agents, onStop, onTerminal }) {
  const panel = root.querySelector("#ag-run");
  const title = root.querySelector("#ag-run-title");
  const status = root.querySelector("#ag-status");
  const log = root.querySelector("#ag-log");
  const result = root.querySelector("#ag-result");
  const stopBtn = root.querySelector("#ag-stop");
  const clearBtn = root.querySelector("#ag-clear");

  let taskId = 0;
  let next = 0;
  let timer = null;
  let terminal = false;
  let notified = false;
  let lines = [];

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

  function renderTask(task) {
    if (!task) return;
    title.textContent = taskTitle(task, agents);
    const state = task.status || "queued";
    status.textContent = statusText(state);
    status.className = `agents-status ${state}`;
    terminal = TERMINAL.has(state);
    stopBtn.hidden = terminal;
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
      const data = await api.get(
        `/api/agents/tasks/${wanted}/events?after=${next}&limit=1000`);
      if (wanted !== taskId) return;
      for (const event of data.events || []) {
        next = Math.max(next, Number(event.seq) || 0);
        append(event);
      }
      renderTask(data.task);
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
    terminal = false;
    notified = false;
    panel.hidden = false;
    log.textContent = "";
    result.hidden = true;
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
