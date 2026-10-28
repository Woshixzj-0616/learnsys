// 今日：学习工作台首页 —— 今日目标、六级断点、行动卡、本周、全部工具、时间线。
import { api } from "../api.js";
import { getModes } from "../modes.js";
import { plain } from "../markdown.js";
import {
  charsParts, escapeHtml, minutesParts, timeOf, toast,
} from "../ui.js";

const WEEK_NAMES = "日一二三四五六";
let studySub = "";
const ACTION_ICONS = {
  due: "↻", train: "✍", cet6: "♪", materials: "▤", weak: "◈",
};

export async function mount(ctx) {
  ctx.setSub("");
  ctx.setActions("");
  document.title = "今日 · 学习工作台";

  const [overview, today, settings, reviewStats] = await Promise.all([
    api.get("/api/overview"),
    api.get("/api/today"),
    api.get("/api/settings").catch(() => null),
    api.get("/api/review/stats").catch(() => null),
  ]);

  renderOnboarding(settings);
  renderHero(overview);
  renderContinue(today.cet6 || []);
  renderPlugins(ctx, overview, settings);
  renderStats(today, reviewStats || {});
  renderActions(today.actions || []);
  renderWeek(overview.week || {});
  renderAchievements(overview.achievements || []);
  renderTimeline(today.asks || []);
  renderFocus(today.focus || {});
  renderCet6(today.cet6 || []);
  bindAsk();
  bindWeekTips();
  bindGo();
  applyScene();
  window.addEventListener("learnsys:modes", applyScene);
}

export function unmount() {
  window.removeEventListener("learnsys:modes", applyScene);
}

function bindGo() {
  document.querySelectorAll("[data-go]").forEach((node) => {
    node.addEventListener("click", () => { location.hash = node.dataset.go; });
  });
}

function bindAsk() {
  const form = document.getElementById("hero-ask");
  const input = document.getElementById("hero-ask-input");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input?.value.trim();
    if (!text) { input?.focus(); return; }
    location.hash = `#/ask?prompt=${encodeURIComponent(text)}`;
  });
}

function applyScene() {
  const work = getModes().scene === "work";
  const sub = document.getElementById("stage-sub");
  if (sub) {
    sub.textContent = work
      ? "把整件事派出去：Agent 中枢负责执行，浏览器和运行记录都在下面。"
      : studySub;
  }
  document.querySelectorAll("#plugin-grid .tool-card").forEach((node) => {
    node.dataset.sceneRank = work && ["agents", "browser", "agentruns", "materials"].includes(node.dataset.id)
      ? "0" : "1";
  });
  const grid = document.getElementById("plugin-grid");
  if (!grid) return;
  const cards = [...grid.children];
  cards.sort((a, b) => Number(a.dataset.sceneRank || 1) - Number(b.dataset.sceneRank || 1));
  cards.forEach((node) => grid.appendChild(node));
}

function renderOnboarding(settings) {
  const panel = document.getElementById("onboarding");
  if (!panel) return;
  panel.hidden = settings?.agent?.ready !== false;
}

function greeting(name) {
  const hour = new Date().getHours();
  const part = hour < 6 ? "夜深了" : hour < 11 ? "早上好" : hour < 14 ? "中午好"
    : hour < 18 ? "下午好" : "晚上好";
  return name ? `${part}，${name}` : part;
}

function renderHero(overview) {
  const today = overview.today || {};
  const total = overview.total || {};
  const streak = Number(overview.streak || 0);
  const tasks = Array.isArray(today.goal_tasks) ? today.goal_tasks : [];
  const done = Number(today.goal_done || 0);
  const totalTasks = Number(today.goal_total || tasks.length || 3);
  const tier = String(today.goal_tier || "none");
  const budget = Number(today.goal_budget_minutes || 0);
  const study = Number(today.study_minutes || 0);
  const measured = Number(today.study_measured || 0);

  document.getElementById("stage-greeting").textContent = greeting(overview.name);
  const sub = document.getElementById("stage-sub");
  if (done >= totalTasks) {
    sub.textContent = "三件事都做完了。今天超额完成，第三件复盘也拿下了。";
  } else if (tier === "met") {
    sub.textContent = "今天已经达标。第三件复盘是加分项，不做也不影响。";
  } else if (done > 0) {
    sub.textContent = `完成 ${done} 件，再做一件就达标 —— 不用盯着分钟数。`;
  } else if (streak >= 7) {
    sub.textContent = `连续 ${streak} 天。今天先挑一件开始，别让这条线断。`;
  } else {
    sub.textContent = "做完两件算达标，第三件复盘是加分项。";
  }
  studySub = sub.textContent;

  document.getElementById("streak-num").textContent = String(streak);
  document.getElementById("level-chip").textContent =
    `Lv.${total.level || 1} · ${total.title || "网络小白"}`;

  const line = document.getElementById("goal-line");
  if (line) {
    if (done >= totalTasks) line.textContent = "今天的目标已经达成";
    else if (tier === "met") line.textContent = "今天已达标 · 第三件是加分";
    else line.textContent = `已完成 ${done} / ${totalTasks} 件 · 两件达标`;
  }

  const root = document.getElementById("goal-tasks");
  if (root) {
    root.innerHTML = tasks.map((task) => `
      <a class="goal-task${task.done ? " done" : ""}" href="${escapeHtml(task.href || "#")}">
        <span class="goal-check" aria-hidden="true">✓</span>
        <span class="goal-task-body">
          <span class="goal-task-title">${escapeHtml(task.title || "")}</span>
          <span class="goal-task-meta">${escapeHtml(task.detail || "")}</span>
        </span>
        <span class="goal-task-time">${Number(task.minutes || 0)} 分钟</span>
      </a>`).join("");
  }

  const foot = document.getElementById("goal-foot");
  if (foot) {
    foot.textContent = `预算约 ${budget} 分钟 · 已记录 ${Math.round(study)} 分钟`
      + `（实测 ${Math.round(measured)}）`;
  }

  const percent = totalTasks ? Math.max(0, Math.min(100, done * 100 / totalTasks)) : 0;
  const doneNode = document.getElementById("goal-done");
  if (doneNode) doneNode.textContent = String(done);
  const totalNode = document.getElementById("goal-total");
  if (totalNode) totalNode.textContent = `/ ${totalTasks}`;
  const ring = document.getElementById("goal-fill");
  if (ring) {
    const circumference = 2 * Math.PI * 38;
    ring.style.strokeDasharray = String(circumference);
    ring.style.strokeDashoffset = String(circumference * (1 - percent / 100));
  }
}

function renderContinue(items) {
  const item = items[0];
  const title = document.getElementById("continue-title");
  const sub = document.getElementById("continue-sub");
  const count = document.getElementById("continue-count");
  const last = document.getElementById("continue-last");
  const go = document.getElementById("continue-go");
  const eq = document.getElementById("continue-eq");

  if (!item) {
    title.textContent = "今天还没练六级";
    sub.textContent = "精听 / 写作 / 翻译，挑一项开始";
    count.textContent = "今天 0 个断点";
    last.textContent = "从 25 分钟的微训练开始";
    go.textContent = "去训练 →";
    go.href = "#/cet6";
    if (eq) eq.hidden = true;
    return;
  }

  title.textContent = item.paper || "六级训练";
  sub.textContent = [item.section, item.item].filter(Boolean).join(" · ") || "继续上次的训练";
  count.textContent = `${Number(item.count || 0)} 处断点`;
  last.textContent = item.last ? `最近 ${timeOf(item.last)}` : "今天刚记下";
  go.textContent = "回到断点 →";
  go.href = "#/cet6?paper=" + encodeURIComponent(item.paper_id || item.paper || "");
  if (eq) eq.hidden = false;
}

function renderPlugins(ctx, overview, settings) {
  const prefs = settings?.modules || {};
  const today = overview.today || {};
  const counts = {
    ask: `${today.asks || 0} 问`,
    netlab: `${today.netlab || 0} 个训练`,
    cet6: today.train
      ? `${today.cet6 || 0} 断点 · ${today.train} 训练`
      : `${today.cet6 || 0} 个断点`,
    review: `${today.review || 0} 次复盘`,
    quiz: `${today.quiz || 0} 场测验`,
  };
  const plugins = (ctx.registry || [])
    .filter((m) => m.home && m.status === "ready" && prefs[m.id] !== false)
    .sort((a, b) => Number(a.order || 999) - Number(b.order || 999));
  const grid = document.getElementById("plugin-grid");
  if (!grid) return;
  if (!plugins.length) {
    grid.innerHTML = '<div class="empty">插件都被关掉了 —— 到 <a href="#/plugins">插件中心</a> 打开。</div>';
    return;
  }
  grid.innerHTML = plugins.map((m) => `
    <button class="tool-card" type="button" data-id="${escapeHtml(m.id)}"
      data-go="#/${escapeHtml(m.id)}">
      <span class="tool-icon" aria-hidden="true">${escapeHtml(m.icon || "·")}</span>
      <span class="tool-copy">
        <span class="tool-name">${escapeHtml(m.name)}</span>
        <span class="tool-desc">${escapeHtml(m.tagline || m.note || "")}</span>
      </span>
      <span class="tool-count">${escapeHtml(counts[m.id] || "打开")}</span>
    </button>`).join("");
  bindGo();
}

function renderStats(today, reviewStats = {}) {
  const study = Number(today.study_minutes || 0);
  const measured = Number(today.study_measured || 0);
  const estimated = Number(today.study_estimated || 0);
  const activity = today.activity || {};
  const chars = charsParts(today.transcripts?.chars);
  const imageAsks = (today.asks || []).filter((ask) => ask.kind === "image").length;
  const stats = [
    {
      label: "记录时长",
      value: String(Math.round(study)),
      unit: "分钟",
      note: `实测 ${Math.round(measured)} · 估算 ${Math.round(estimated)}`
        + (Number(activity.breakpoints || 0) > 0
          ? ` · 断点 ${activity.breakpoints} 次` : ""),
    },
    {
      label: "问答",
      value: String(today.ask_count ?? 0),
      unit: "条",
      note: imageAsks ? `今天 ${imageAsks} 条带图` : "今天的提问",
    },
    {
      label: "课堂转写",
      value: String(today.transcripts?.count ?? 0),
      unit: "段",
      note: `${chars.value} ${chars.unit} · 录像 ${today.recordings?.count ?? 0} 段`,
    },
    {
      label: "待复习",
      value: String(today.due_reviews ?? 0),
      unit: "条",
      note: reviewStats.reviewed_today
        ? `今天已复习 ${reviewStats.reviewed_today} 条`
        : (today.due_reviews
          ? "按记忆曲线排到今天"
          : (reviewStats.next_due ? `下张 ${reviewStats.next_due} 到期` : "今天没有到期的")),
    },
  ];
  const root = document.getElementById("today-stats");
  if (!root) return;
  root.innerHTML = stats.map((stat) => `<div class="stat">
      <b>${escapeHtml(stat.value)}<i>${escapeHtml(stat.unit)}</i></b>
      <span>${escapeHtml(stat.label)}</span>
      <em>${escapeHtml(stat.note)}</em>
    </div>`).join("");
}

function renderActions(actions) {
  const root = document.getElementById("today-actions");
  if (!root) return;
  if (!actions.length) { root.hidden = true; return; }
  root.hidden = false;
  root.innerHTML = `<div class="card-head">
      <h2>今天还可以</h2><span class="muted">${actions.length} 件小事</span>
    </div>` + actions.map((item, index) => `
    <button class="action" type="button" data-action-index="${index}">
      <span class="action-ico" aria-hidden="true">${ACTION_ICONS[item.kind] || "→"}</span>
      <span class="action-body">
        <span class="action-title">${escapeHtml(item.title || "")}</span>
        <span class="action-meta">${escapeHtml(item.detail || "")}</span>
      </span>
      <span class="action-label">${escapeHtml(item.label || "去看看")} →</span>
    </button>`).join("");
  root.querySelectorAll("[data-action-index]").forEach((node) => {
    const item = actions[Number(node.dataset.actionIndex)] || {};
    node.addEventListener("click", () => {
      if (item.href) location.hash = item.href;
    });
  });
}

function renderWeek(week) {
  const root = document.getElementById("week-bars");
  if (!root) return;
  const daily = Array.isArray(week.daily) ? week.daily : [];
  const minutesOf = (day) => Number(day.study_minutes ?? day.minutes ?? 0);
  const values = daily.map(minutesOf);
  const max = Math.max(1, ...values);
  const todayKey = new Date().toISOString().slice(0, 10);
  const labels = daily.map((day) => {
    const parsed = new Date(`${day.date}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? "" : WEEK_NAMES[parsed.getDay()];
  });

  if (!daily.length) {
    root.innerHTML = '<div class="hint" style="padding:18px 4px">本周还没有学习投入。</div>';
  } else {
    root.innerHTML = daily.map((day, index) => {
      const minutes = minutesOf(day);
      const height = minutes ? Math.max(4, Math.round((minutes / max) * 100)) : 2;
      const isToday = day.date === todayKey;
      const label = labels[index] || "";
      const goalDone = Number(day.goal_done || 0);
      const goalTotal = Number(day.goal_total || 3);
      const achieved = Boolean(day.goal_achieved);
      const value = index === values.indexOf(max) && minutes ? `<em class="val">${minutes}</em>` : "";
      return `<button class="bar${isToday ? " today" : ""}${achieved ? " achieved" : ""}" type="button"
        style="--h:${height}%;--i:${index}" data-tip="${escapeHtml(label)} · ${minutes} 分钟 · 目标 ${goalDone}/${goalTotal}${isToday ? "（今天）" : ""}">
        <i></i>${value}<span>${escapeHtml(label)}</span>
      </button>`;
    }).join("");
  }

  const total = minutesParts(week.study_minutes ?? week.minutes ?? 0);
  document.getElementById("week-total").textContent = `共 ${total.value} ${total.unit}`;
  document.getElementById("week-extra").textContent =
    `达标 ${Number(week.achieved_days || 0)} / ${Number(week.goal_days || 5)} 天`;
  root.setAttribute("aria-label",
    `本周投入：${daily.map((day, index) => `${labels[index]} ${minutesOf(day)} 分钟`).join("，")}`);
}

function bindWeekTips() {
  const tip = document.getElementById("tip");
  if (!tip) return;
  document.querySelectorAll("#week-bars .bar").forEach((bar) => {
    const show = () => {
      tip.textContent = bar.dataset.tip || "";
      const rect = bar.getBoundingClientRect();
      tip.style.left = `${rect.left + rect.width / 2}px`;
      tip.style.top = `${rect.top - 8}px`;
      tip.classList.add("is-on");
    };
    const hide = () => tip.classList.remove("is-on");
    bar.addEventListener("mouseenter", show);
    bar.addEventListener("mouseleave", hide);
    bar.addEventListener("focus", show);
    bar.addEventListener("blur", hide);
  });
}

function renderAchievements(items) {
  const earned = items.filter((item) => item.earned);
  const count = document.getElementById("ach-count");
  if (count) count.textContent = `${earned.length} / ${items.length}`;
  const root = document.getElementById("achievements");
  if (!root) return;
  const shown = [...earned, ...items.filter((item) => !item.earned)].slice(0, 8);
  root.innerHTML = shown.map((item) => `
    <div class="achievement ${item.earned ? "earned" : "locked"}" title="${escapeHtml(item.desc)}">
      <span class="ach-dot" aria-hidden="true">${item.earned ? "✓" : "·"}</span>
      <span class="ach-name">${escapeHtml(item.name)}</span>
      <span class="ach-progress">${item.value}/${item.target}</span>
    </div>`).join("");
}

function renderTimeline(asks) {
  const root = document.getElementById("today-timeline");
  const count = document.getElementById("timeline-count");
  if (!root) return;
  if (!asks.length) {
    if (count) count.textContent = "";
    root.innerHTML = `<div class="empty"><strong>今天还没有问答</strong>
      从问一问开始，每个问题都会自动记进这条时间线。</div>`;
    return;
  }
  if (count) count.textContent = `最近 ${asks.length} 条`;
  root.innerHTML = `<div class="timeline">${asks.map((ask) => {
    const tag = ask.kind === "image" ? '<span class="timeline-tag">图</span>' : "";
    return `<button class="timeline-item${ask.kind === "image" ? " is-image" : ""}"
        type="button" data-conv="${ask.conversation_id || ""}">
      <span class="timeline-time">${escapeHtml(timeOf(ask.ts))}</span>
      <span class="timeline-q">${escapeHtml(ask.question || "")}${tag}</span>
      <span class="timeline-a">${escapeHtml(plain(ask.answer, 180))}</span>
    </button>`;
  }).join("")}</div>`;

  root.querySelectorAll("[data-conv]").forEach((node) => {
    node.addEventListener("click", () => {
      const id = node.dataset.conv;
      if (id) {
        location.hash = `#/ask/${id}`;
      } else {
        toast("这条是快捷栏问的，暂时只能在横栏历史里看");
      }
    });
  });
}

function renderFocus(focus) {
  const body = document.getElementById("focus-body");
  if (!body) return;
  const apps = Array.isArray(focus.apps) ? focus.apps : [];
  const parts = minutesParts(focus.minutes);
  body.innerHTML = `
    <div class="panel-row"><span>专注时长</span><span>${escapeHtml(parts.value)} ${escapeHtml(parts.unit)}</span></div>
    <div class="panel-row"><span>窗口切换</span><span>${escapeHtml(focus.switches ?? 0)} 次</span></div>
    ${apps.length
      ? apps.map(([name, mins]) => `<div class="panel-row">
          <span>${escapeHtml(name)}</span><span>${Number(mins).toFixed(0)} 分钟</span></div>`).join("")
      : '<div class="hint" style="padding-top:10px">今天还没有开始录像。按 Alt+Q 打开快捷栏点「录像」，或在托盘菜单开始。</div>'}`;
}

function renderCet6(items) {
  if (!items.length) return;
  const panel = document.getElementById("cet6-panel");
  const body = document.getElementById("cet6-body");
  if (!panel || !body) return;
  panel.hidden = false;
  body.innerHTML = items.map((item) => `
    <div class="panel-row">
      <span>${escapeHtml(item.paper || "六级")} · ${escapeHtml(item.section || "")}${item.item ? " · " + escapeHtml(item.item) : ""}</span>
      <span>${item.count} 个断点</span>
    </div>`).join("");
  body.querySelectorAll(".panel-row").forEach((row, index) => {
    const item = items[index] || {};
    const paper = item.paper_id || item.paper || "";
    row.style.cursor = "pointer";
    row.title = "回到这份试卷";
    row.addEventListener("click", () => {
      if (!paper) return;
      location.hash = `#/cet6?paper=${encodeURIComponent(paper)}`;
    });
  });
}
