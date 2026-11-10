// 今日目标卡：三格渲染 + 训练格的「换一个」。只碰 DOM，不请求接口。
import { escapeHtml } from "../ui.js";

const SWAP_KEY = "learnsys_goal_swap";

let goalTasks = [];
let goalDate = "";
let goalSwap = 0;

function readSwap(day) {
  try {
    return Math.max(0, Number(localStorage.getItem(`${SWAP_KEY}:${day}`)) || 0);
  } catch {
    return 0;
  }
}

function saveSwap(day, value) {
  try { localStorage.setItem(`${SWAP_KEY}:${day}`, String(Number(value) || 0)); } catch { /* 忽略 */ }
}

/* 输出格可以带备选：换一个只是换推荐，完成判定仍是「今天动过训练」。 */
function goalView(task) {
  const alts = Array.isArray(task.alternatives) ? task.alternatives : [];
  if (task.id !== "output" || task.done || alts.length < 2) {
    return { task, canSwap: false };
  }
  const index = ((goalSwap % alts.length) + alts.length) % alts.length;
  const alt = alts[index] || {};
  return {
    canSwap: true,
    task: {
      ...task,
      title: alt.title || task.title,
      detail: alt.detail || task.detail,
      href: alt.href || task.href,
      label: alt.label || task.label,
      minutes: alt.minutes ?? task.minutes,
    },
  };
}

function paint() {
  const root = document.getElementById("goal-tasks");
  if (!root) return;
  root.innerHTML = goalTasks.map((task) => {
    const view = goalView(task);
    const item = view.task;
    return `<div class="task-row">
      <a class="task${item.done ? " done" : ""}" href="${escapeHtml(item.href || "#")}">
        <span class="task-check" aria-hidden="true">✓</span>
        <span class="task-body">
          <span class="task-title">${escapeHtml(item.title || "")}</span>
          <span class="task-meta">${escapeHtml(item.detail || "")}</span>
        </span>
        <span class="task-min">${Number(item.minutes || 0)} 分钟</span>
        <span class="task-go">${escapeHtml(item.label || "打开")} →</span>
      </a>
      ${view.canSwap ? '<button class="task-swap" type="button" data-swap-goal title="换一个今天的训练任务">换一个</button>' : ""}
    </div>`;
  }).join("");
}

/** 渲染三格；`day` 用来记住当天的换卡位置。 */
export function renderGoals(tasks, day = "") {
  goalTasks = Array.isArray(tasks) ? tasks : [];
  goalDate = day || "";
  goalSwap = readSwap(goalDate);
  paint();
}

/** 页面挂载时调用一次；容器上只绑一个委托监听。 */
export function bindGoals() {
  const root = document.getElementById("goal-tasks");
  if (!root || root.dataset.swapBound) return;
  root.dataset.swapBound = "1";
  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-swap-goal]");
    if (!button) return;
    const output = goalTasks.find((task) => task.id === "output");
    const count = output?.alternatives?.length || 0;
    if (count < 2) return;
    goalSwap = (goalSwap + 1) % count;
    saveSwap(goalDate, goalSwap);
    paint();
  });
}
