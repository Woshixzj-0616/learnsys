// 今日：学习工作台首页 —— 今日目标、简报、接着上次、问答轨道、本周。
// 只放「今天会变」的内容；工具导航留在侧栏，常设清单留在各自页面。
import { api } from "../api.js";
import { plain } from "../markdown.js";
import { escapeHtml, minutesParts, timeOf, toast } from "../ui.js";
import { renderDomains } from "./today-domains.js";

const WEEK_NAMES = "日一二三四五六";
const PERIODS = ["凌晨", "上午", "下午", "晚上"];

export async function mount(ctx) {
  ctx.setSub("");
  ctx.setActions("");
  document.title = "今日 · 学习工作台";

  const [overview, today, settings, briefing, home] = await Promise.all([
    api.get("/api/overview"),
    api.get("/api/today"),
    api.get("/api/settings").catch(() => null),
    api.get("/api/briefing/today").catch(() => null),
    api.get("/api/home").catch(() => null),
  ]);

  const goalTasks = overview.today?.goal_tasks || [];
  renderOnboarding(settings);
  renderHero(overview);
  renderDomains(home);
  renderContinue(today.cet6 || [], goalTasks);
  renderAlts(today.actions || [], (today.cet6 || [])[0]);
  renderBriefing(briefing, settings);
  renderWeek(overview.week || {});
  renderFacts(today, overview.today || {});
  renderAchievements(overview.achievements || []);
  renderTimeline(today.asks || [], Number(today.ask_count || 0));
  renderFocus(today.focus || {});
  bindAsk();
  bindWeekTips();
}

export function unmount() {}

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

function todayKey() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function monthDay(day) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(day || ""));
  return match ? `${Number(match[2])} 月 ${Number(match[3])} 日` : "";
}

/* ---------- Hero ---------- */

function renderHero(overview) {
  const today = overview.today || {};
  const total = overview.total || {};
  const streak = Number(overview.streak || 0);
  const tasks = Array.isArray(today.goal_tasks) ? today.goal_tasks : [];
  const done = Number(today.goal_done || 0);
  const totalTasks = Number(today.goal_total || tasks.length || 3);
  const tier = String(today.goal_tier || "none");

  document.getElementById("stage-greeting").textContent = greeting(overview.name);
  document.getElementById("streak-num").textContent = String(streak);
  document.getElementById("level-chip").textContent =
    `Lv.${total.level || 1} · ${total.title || "网络小白"}`;

  const state = document.getElementById("goal-state");
  if (state) {
    if (done >= totalTasks) state.textContent = "三件都做完了 · 今天超额完成";
    else if (tier === "met") state.textContent = "今天已达标 · 第三件复盘是加分";
    else if (done > 0) state.textContent = `完成 ${done} 件 · 再做一件就达标`;
    else if (streak >= 7) state.textContent = `连续 ${streak} 天 · 今天先挑一件`;
    else state.textContent = "做完两件算达标，第三件是加分";
  }

  const root = document.getElementById("goal-tasks");
  if (root) {
    root.innerHTML = tasks.map((task) => `
      <a class="task${task.done ? " done" : ""}" href="${escapeHtml(task.href || "#")}">
        <span class="task-check" aria-hidden="true">✓</span>
        <span class="task-body">
          <span class="task-title">${escapeHtml(task.title || "")}</span>
          <span class="task-meta">${escapeHtml(task.detail || "")}</span>
        </span>
        <span class="task-min">${Number(task.minutes || 0)} 分钟</span>
        <span class="task-go">${escapeHtml(task.label || "打开")} →</span>
      </a>`).join("");
  }

  const percent = totalTasks ? Math.max(0, Math.min(100, done * 100 / totalTasks)) : 0;
  document.getElementById("goal-done").textContent = String(done);
  document.getElementById("goal-total").textContent = `/ ${totalTasks}`;
  const ring = document.getElementById("goal-fill");
  if (ring) {
    const circumference = 2 * Math.PI * 32;
    ring.style.strokeDasharray = String(circumference);
    ring.style.strokeDashoffset = String(circumference * (1 - percent / 100));
  }
}

/* ---------- 接着上次 + 备选行动 ---------- */

function renderContinue(items, goalTasks) {
  const item = items[0];
  const title = document.getElementById("continue-title");
  const sub = document.getElementById("continue-sub");
  const count = document.getElementById("continue-count");
  const last = document.getElementById("continue-last");
  const state = document.getElementById("continue-state");
  const go = document.getElementById("continue-go");
  if (!title || !sub || !count || !last || !go) return;

  const listenDone = (goalTasks || []).some((task) => task.id === "listen" && task.done);

  if (!item) {
    title.textContent = "今天还没练六级";
    sub.textContent = "精听 / 写作 / 翻译，挑一项开始";
    count.textContent = "今天 0 个断点";
    last.textContent = "从 25 分钟的微训练开始";
    if (state) state.textContent = "";
    go.textContent = "去训练 →";
    go.href = "#/cet6";
    return;
  }

  title.textContent = item.paper || "六级训练";
  sub.textContent = [item.section, item.item].filter(Boolean).join(" · ") || "继续上次的训练";
  count.textContent = `${Number(item.count || 0)} 处断点`;
  last.textContent = item.last ? `最近 ${timeOf(item.last)}` : "今天刚记下";
  if (state) state.textContent = listenDone ? "今天精听已达标" : "今天还没练";
  go.textContent = "回到断点 →";
  go.href = "#/cet6?paper=" + encodeURIComponent(item.paper_id || item.paper || "");
}

function renderAlts(actions, continueItem) {
  const root = document.getElementById("continue-alts");
  if (!root) return;

  const seen = new Set();
  const continueHref = continueItem
    ? "#/cet6?paper=" + encodeURIComponent(continueItem.paper_id || continueItem.paper || "")
    : "";
  if (continueHref) seen.add(continueHref);

  const rest = [];
  for (const action of actions) {
    const href = String(action?.href || "");
    if (!href || seen.has(href)) continue;
    seen.add(href);
    rest.push(action);
    if (rest.length >= 2) break;
  }

  root.innerHTML = rest.map((action) => `
    <a class="alt" href="${escapeHtml(action.href)}">
      <span class="alt-label">也可以</span>
      <span class="alt-title">${escapeHtml(action.title || "")}</span>
      <span class="alt-meta">${escapeHtml(action.detail || "")}</span>
      <span class="alt-go">${escapeHtml(action.label || "去看看")} →</span>
    </a>`).join("");
}

/* ---------- 今日简报 ---------- */

function renderBriefing(data, settings) {
  const root = document.getElementById("today-briefing");
  if (!root) return;
  if (settings?.briefing?.enabled === false || !data) {
    root.hidden = true;
    return;
  }

  const items = Array.isArray(data.items) ? data.items : [];
  const status = String(data.status || "missing");
  const titleOf = (item) => item.title_zh || item.title || "";
  const srcOf = (item) => {
    const time = String(item.published_at || "").slice(11, 16);
    return [item.source, time].filter(Boolean).join(" · ");
  };

  const eyebrow = document.getElementById("brief-eyebrow");
  const title = document.getElementById("brief-title");
  const meta = document.getElementById("brief-meta");
  const main = document.getElementById("brief-main");
  if (!eyebrow || !title || !meta || !main) return;

  root.hidden = false;
  eyebrow.textContent = `每日简报 · ${monthDay(data.day) || "今天"}`;
  title.textContent = items.length
    ? `今天值得知道的 ${Number(data.item_count || items.length)} 件事`
    : (["pending", "running"].includes(status) ? "今天的简报正在生成" : "今天的简报还没生成");

  const updated = String(data.updated_at || data.created_at || "").slice(11, 16);
  const sources = data.source_total
    ? `${Number(data.source_ok || 0)} / ${Number(data.source_total)} 源`
    : "";
  meta.textContent = items.length
    ? [status === "partial" ? "部分完成" : "", updated ? `已生成 ${updated}` : "", sources]
      .filter(Boolean).join(" · ")
    : ({
      scheduled: `每天 ${data.generate_at || "07:30"} 自动生成`,
      pending: "正在排队",
      running: "正在抓取与写摘要",
      failed: "上次生成失败",
    }[status] || "");

  if (!items.length) {
    const hint = data.error || ({
      scheduled: `每天 ${data.generate_at || "07:30"} 自动生成 12–15 条，也可以现在去生成。`,
      pending: "正在排队，通常半分钟到两分钟。",
      running: "正在抓取与写摘要，通常半分钟到两分钟。",
      failed: "上次生成失败，去简报页重试。",
    }[status] || "今天还没有简报，去简报页生成一份。");
    main.innerHTML = `<div class="brief-empty">
      <p>${escapeHtml(hint)}</p>
      <a class="btn" href="#/briefing">去简报页 →</a>
    </div>`;
    return;
  }

  const lead = items[0];
  const side = items.slice(1, 4);
  main.innerHTML = `
    <a class="brief-lead" href="#/briefing">
      <span class="tag">${escapeHtml(lead.category_label || "")}</span>
      <h3>${escapeHtml(titleOf(lead))}</h3>
      ${lead.summary ? `<p>${escapeHtml(lead.summary)}</p>` : ""}
      <span class="src">${escapeHtml(srcOf(lead))}</span>
    </a>
    <div class="brief-side">
      ${side.map((item) => `
        <a class="brief-row" href="#/briefing">
          <span class="tag">${escapeHtml(item.category_label || "")}</span>
          <h4>${escapeHtml(titleOf(item))}</h4>
          <span class="src">${escapeHtml(srcOf(item))}</span>
        </a>`).join("")}
    </div>`;
}

/* ---------- 本周 + 今天一行 ---------- */

function renderWeek(week) {
  const root = document.getElementById("week-bars");
  if (!root) return;
  const daily = Array.isArray(week.daily) ? week.daily : [];
  const minutesOf = (day) => Number(day.study_minutes ?? day.minutes ?? 0);
  const values = daily.map(minutesOf);
  const max = Math.max(1, ...values);
  const key = todayKey();
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
      const isToday = day.date === key;
      const achieved = Boolean(day.goal_achieved);
      const label = labels[index] || "";
      const goalDone = Number(day.goal_done || 0);
      const goalTotal = Number(day.goal_total || 3);
      const value = minutes && (minutes === max || isToday)
        ? `<em class="val">${Math.round(minutes)}</em>` : "";
      return `<button class="bar${isToday ? " today" : ""}${achieved ? " achieved" : ""}" type="button"
        style="--h:${height}%;--i:${index}"
        data-tip="${escapeHtml(label)} · ${Math.round(minutes)} 分钟 · 目标 ${goalDone}/${goalTotal}${isToday ? "（今天）" : ""}">
        <i></i>${value}<span>${escapeHtml(label)}</span>
      </button>`;
    }).join("");
  }

  const total = minutesParts(week.study_minutes ?? week.minutes ?? 0);
  document.getElementById("week-total").textContent = `共 ${total.value} ${total.unit}`;
  document.getElementById("week-extra").textContent =
    `达标 ${Number(week.achieved_days || 0)} / ${Number(week.goal_days || 5)} 天`;
  const active = document.getElementById("week-active");
  if (active) active.textContent = `活跃 ${Number(week.active_days || 0)} / 7 天`;
  root.setAttribute("aria-label",
    `本周投入：${daily.map((day, index) => `${labels[index]} ${Math.round(minutesOf(day))} 分钟`).join("，")}`);
}

function renderFacts(today, overviewToday = {}) {
  const root = document.getElementById("today-facts");
  if (!root) return;
  const activity = today.activity || {};
  const cet6List = Array.isArray(today.cet6) ? today.cet6 : [];
  const cet6Total = cet6List.reduce((sum, item) => sum + Number(item.count || 0), 0);
  const facts = [
    { value: Number(today.ask_count || 0), label: "问答" },
    { value: cet6Total, label: "听力断点" },
    {
      value: Number(overviewToday.netlab || 0) + Number(activity.trains || 0),
      label: "训练",
    },
    {
      value: Math.round(Number(today.study_measured || 0)),
      unit: "分钟",
      label: "实测专注",
    },
  ];
  root.innerHTML = facts.map((fact) => `<div class="fact">
      <b>${escapeHtml(String(fact.value))}${fact.unit ? `<i>${escapeHtml(fact.unit)}</i>` : ""}</b>
      <span>${escapeHtml(fact.label)}</span>
    </div>`).join("");
}

/* ---------- 成就 ---------- */

function renderAchievements(items) {
  const summary = document.getElementById("ach-summary");
  const root = document.getElementById("achievements");
  if (!root) return;
  const earned = items.filter((item) => item.earned);
  const next = items.find((item) => !item.earned);
  if (summary) {
    summary.textContent = `${earned.length} / ${items.length}`
      + (next ? ` · 下一项 ${next.name} ${Number(next.value || 0)}/${Number(next.target || 0)}` : "");
  }
  const shown = [...earned, ...items.filter((item) => !item.earned)].slice(0, 8);
  root.innerHTML = shown.map((item) => `
    <div class="ach-row ${item.earned ? "earned" : "locked"}" title="${escapeHtml(item.desc || "")}">
      <span class="dot-ok" aria-hidden="true">${item.earned ? "✓" : "·"}</span>
      <span class="name">${escapeHtml(item.name || "")}</span>
      <span class="prog">${Number(item.value || 0)}/${Number(item.target || 0)}</span>
    </div>`).join("");
}

/* ---------- 今天的问答：按时段分组的轨道 ---------- */

function looksCode(text) {
  const value = String(text || "");
  return /\n/.test(value)
    || /```|#include|^\s*(def|class|function|import|from|package)\b/m.test(value);
}

function periodOf(stamp) {
  const hour = Number(String(stamp || "").slice(11, 13));
  if (!Number.isFinite(hour)) return "其他";
  if (hour < 6) return PERIODS[0];
  if (hour < 12) return PERIODS[1];
  if (hour < 18) return PERIODS[2];
  return PERIODS[3];
}

function questionLabel(ask) {
  const question = String(ask.question || "").trim();
  if (!looksCode(question)) return plain(question, 120);
  const lines = question.split("\n").filter((line) => line.trim()).length;
  const lang = /#include|std::|cout|cin|class\s+\w+/.test(question) ? "C++ " : "";
  return lang
    ? `粘贴了一段 ${lang}代码（约 ${lines} 行）`
    : `粘贴了一段代码（约 ${lines} 行）`;
}

function renderTimeline(asks, askCount) {
  const root = document.getElementById("today-timeline");
  const sub = document.getElementById("timeline-sub");
  if (!root) return;

  const shown = asks.slice(0, 6);
  const total = Math.max(askCount, asks.length);
  if (sub) {
    sub.textContent = shown.length
      ? (total > shown.length ? `${total} 条记录 · 最近 ${shown.length} 条` : `${total} 条记录`)
      : "今天还没有问答";
  }
  if (!shown.length) {
    root.innerHTML = `<div class="empty"><strong>今天还没有问答</strong>
      从问一问开始，每个问题都会自动记进这条时间线。</div>`;
    return;
  }

  const groups = [];
  for (const ask of shown) {
    const label = periodOf(ask.ts);
    let group = groups[groups.length - 1];
    if (!group || group.label !== label) {
      group = { label, items: [] };
      groups.push(group);
    }
    group.items.push(ask);
  }

  root.innerHTML = groups.map((group) => `
    <div class="tl-group">
      <div class="tl-group-head">
        <b>${escapeHtml(group.label)}</b><i></i><span>${group.items.length} 条</span>
      </div>
      ${group.items.map((ask) => {
        const image = ask.kind === "image";
        const code = !image && looksCode(ask.question);
        const tag = image ? '<span class="tl-tag">图</span>'
          : code ? '<span class="tl-tag">代码</span>' : "";
        const conv = ask.conversation_id ? String(ask.conversation_id) : "";
        return `<a class="tl-item${image ? " is-image" : code ? " is-code" : ""}"
            href="${conv ? `#/ask/${conv}` : "#/ask"}" data-conv="${escapeHtml(conv)}">
          <span class="tl-time">${escapeHtml(timeOf(ask.ts))}</span>
          <span class="tl-rail"><i></i></span>
          <span class="tl-body">
            <span class="tl-q">${escapeHtml(questionLabel(ask))}${tag}</span>
            <span class="tl-a">${escapeHtml(plain(ask.answer, 260))}</span>
          </span>
          <span class="tl-open">打开 →</span>
        </a>`;
      }).join("")}
    </div>`).join("");

  root.querySelectorAll("[data-conv]").forEach((node) => {
    if (node.dataset.conv) return;
    node.addEventListener("click", (event) => {
      event.preventDefault();
      toast("这条是快捷栏问的，暂时只能在横栏历史里看");
    });
  });
}

/* ---------- 专注（有数据才显示） ---------- */

function renderFocus(focus) {
  const card = document.getElementById("focus-card");
  const body = document.getElementById("focus-body");
  const meta = document.getElementById("focus-meta");
  if (!card || !body) return;
  const apps = Array.isArray(focus.apps) ? focus.apps : [];
  const minutes = Number(focus.minutes || 0);
  const switches = Number(focus.switches || 0);
  if (!minutes && !switches && !apps.length) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const parts = minutesParts(minutes);
  if (meta) meta.textContent = `${parts.value} ${parts.unit} · 切换 ${switches} 次`;
  body.innerHTML = `
    <div class="panel-row"><span>专注时长</span><span>${escapeHtml(parts.value)} ${escapeHtml(parts.unit)}</span></div>
    <div class="panel-row"><span>窗口切换</span><span>${switches} 次</span></div>
    ${apps.slice(0, 4).map(([name, mins]) => `<div class="panel-row">
      <span>${escapeHtml(name)}</span><span>${Number(mins).toFixed(0)} 分钟</span></div>`).join("")}`;
}

/* ---------- 本周柱状图提示 ---------- */

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
