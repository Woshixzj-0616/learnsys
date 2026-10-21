// 学习台：舞台首页 —— 学习点/连续天数/等级、插件卡片、时间线、专注、成就。
import { api } from "../api.js";
import { plain } from "../markdown.js";
import {
  charsParts, escapeHtml, minutesParts, timeOf, toast, todayLabel,
} from "../ui.js";

export async function mount(ctx) {
  ctx.setSub(todayLabel());
  ctx.setActions('<a class="btn btn-primary" href="#/ask">新问题</a>');

  const [overview, today, conversations, settings] = await Promise.all([
    api.get("/api/overview"),
    api.get("/api/today"),
    api.get("/api/conversations?limit=8").catch(() => ({ items: [] })),
    api.get("/api/settings").catch(() => null),
  ]);

  renderOnboarding(settings);
  renderHero(overview);
  renderPlugins(ctx, overview, settings);
  renderStats(today);
  renderWeek(overview.week || {});
  renderAchievements(overview.achievements || []);
  renderTimeline(today.asks || []);
  renderFocus(today.focus || {});
  renderCet6(today.cet6 || []);

  const latest = (conversations.items || []).find((item) => item.messages > 0);
  const continueButton = ctx.root.querySelector("#continue-last");
  continueButton?.addEventListener("click", () => {
    if (latest) {
      location.hash = `#/ask/${latest.id}`;
    } else {
      toast("还没有会话，先问一个问题吧");
      location.hash = "#/ask";
    }
  });

  ctx.root.querySelectorAll("[data-go]").forEach((node) => {
    node.addEventListener("click", () => { location.hash = node.dataset.go; });
  });
}

function renderOnboarding(settings) {
  const panel = document.getElementById("onboarding");
  if (!panel) return;
  const ready = settings?.agent?.ready;
  panel.hidden = ready !== false;      // 只有明确「没配好」才显示首次引导
}

function greeting(name) {
  const hour = new Date().getHours();
  const part = hour < 6 ? "夜深了" : hour < 11 ? "早上好" : hour < 14 ? "中午好"
    : hour < 18 ? "下午好" : "晚上好";
  return name ? `${part}，${name}` : `${part}`;
}

function renderHero(overview) {
  const today = overview.today || {};
  const total = overview.total || {};
  const streak = Number(overview.streak || 0);
  document.getElementById("stage-greeting").textContent = greeting(overview.name);

  const title = document.querySelector(".stage-title");
  const sub = document.getElementById("stage-sub");
  if (today.percent >= 100) {
    title.textContent = "今日目标达成。";
    sub.textContent = "学习点已经攒够 —— 想再往前走，去训练场开一格。";
  } else if (streak >= 7) {
    title.textContent = `连续 ${streak} 天，稳住。`;
    sub.textContent = "把今天的目标收掉，就是给这条连续线续命。";
  } else {
    title.textContent = "今天，练一格。";
    sub.textContent = "问出去、听清楚、抓包看明白 —— 每天留下一点能看见的进度。";
  }

  const goal = Number(today.goal || 100);
  document.getElementById("goal-text").textContent = `${today.xp || 0} / ${goal}`;
  document.getElementById("goal-fill").style.width = `${Math.min(100, today.percent || 0)}%`;
  const left = Math.max(0, goal - Number(today.xp || 0));
  document.getElementById("goal-note").textContent = left
    ? `再攒 ${left} 学习点到今天的目标`
    : "今天的目标已经完成，继续保持";

  document.getElementById("streak-num").textContent = String(streak);
  document.getElementById("level-badge").textContent = `Lv.${total.level || 1}`;
  document.getElementById("level-title").textContent = total.title || "网络小白";
  document.getElementById("level-fill").style.width = `${Math.min(100, total.percent || 0)}%`;
  document.getElementById("level-note").textContent =
    `累计 ${total.xp || 0} 点 · 再攒 ${Math.max(0, (total.need || 0) - (total.into || 0))} 点升级`;
}

function renderPlugins(ctx, overview, settings) {
  const prefs = settings?.modules || {};
  const today = overview.today || {};
  const counts = {
    ask: `${today.asks || 0} 问`,
    netlab: `${today.netlab || 0} 个训练`,
    cet6: `${today.cet6 || 0} 个断点`,
    review: `${today.review || 0} 次复盘`,
    quiz: `${today.quiz || 0} 场测验`,
  };
  const plugins = (ctx.registry || [])
    .filter((m) => m.home && m.status === "ready" && prefs[m.id] !== false)
    .sort((a, b) => Number(a.order || 999) - Number(b.order || 999));
  const grid = document.getElementById("plugin-grid");
  if (!plugins.length) {
    grid.innerHTML = '<div class="empty">插件都被关掉了 —— 到 <a href="#/plugins">插件中心</a> 打开。</div>';
    return;
  }
  grid.innerHTML = plugins.map((m) => `
    <button class="plugin-card" type="button" data-go="#/${escapeHtml(m.id)}">
      <span class="plugin-icon" aria-hidden="true">${escapeHtml(m.icon || "·")}</span>
      <span class="plugin-name">${escapeHtml(m.name)}</span>
      <span class="plugin-cat">${escapeHtml(m.category || "插件")}</span>
      <span class="plugin-tagline">${escapeHtml(m.tagline || m.note || "")}</span>
      <span class="plugin-foot">
        <span class="plugin-count">${escapeHtml(counts[m.id] || "打开")}</span>
        <span class="plugin-open">进入 →</span>
      </span>
    </button>`).join("");
  grid.querySelectorAll("[data-go]").forEach((node) => {
    node.addEventListener("click", () => { location.hash = node.dataset.go; });
  });
}

function renderStats(today) {
  const focus = minutesParts(today.focus?.minutes);
  const chars = charsParts(today.transcripts?.chars);
  const imageAsks = (today.asks || []).filter((ask) => ask.kind === "image").length;
  const stats = [
    {
      label: "专注",
      value: focus.value,
      unit: focus.unit,
      note: `切换 ${today.focus?.switches ?? 0} 次`,
    },
    {
      label: "问答",
      value: String(today.ask_count ?? 0),
      unit: "条",
      note: imageAsks ? `最近 10 条里 ${imageAsks} 条带图` : "今天的提问",
    },
    {
      label: "课堂转写",
      value: String(today.transcripts?.count ?? 0),
      unit: "段",
      note: `${chars.value} ${chars.unit}`,
    },
    {
      label: "待复习",
      value: String(today.due_reviews ?? 0),
      unit: "条",
      note: today.due_reviews ? "收藏后到期的问答" : "今天没有到期的",
    },
  ];
  document.getElementById("today-stats").innerHTML = stats.map((stat) => `<div class="stat">
      <div class="stat-label">${escapeHtml(stat.label)}</div>
      <div class="stat-value">${escapeHtml(stat.value)}<small>${escapeHtml(stat.unit)}</small></div>
      <div class="stat-note">${escapeHtml(stat.note)}</div>
    </div>`).join("");
}

function renderWeek(week) {
  const minutes = minutesParts(week.minutes || 0);
  document.getElementById("week-body").innerHTML = `
    <div class="panel-row"><span>活跃天数</span><span>${escapeHtml(String(week.active_days || 0))} / 7</span></div>
    <div class="panel-row"><span>专注时长</span><span>${escapeHtml(minutes.value)} ${escapeHtml(minutes.unit)}</span></div>
    <div class="panel-row"><span>问答</span><span>${escapeHtml(String(week.asks || 0))} 条</span></div>`;
}

function renderAchievements(items) {
  const earned = items.filter((item) => item.earned);
  document.getElementById("ach-count").textContent = `${earned.length} / ${items.length}`;
  const shown = [...earned, ...items.filter((item) => !item.earned)].slice(0, 8);
  document.getElementById("achievements").innerHTML = shown.map((item) => `
    <div class="achievement ${item.earned ? "earned" : "locked"}" title="${escapeHtml(item.desc)}">
      <span class="ach-dot" aria-hidden="true">${item.earned ? "✓" : "·"}</span>
      <span class="ach-name">${escapeHtml(item.name)}</span>
      <span class="ach-progress">${item.value}/${item.target}</span>
    </div>`).join("");
}

function renderTimeline(asks) {
  const root = document.getElementById("today-timeline");
  const count = document.getElementById("timeline-count");
  if (!asks.length) {
    count.textContent = "";
    root.innerHTML = `<div class="empty"><strong>今天还没有问答</strong>
      从问一问开始，每个问题都会自动记进这条时间线。</div>`;
    return;
  }
  count.textContent = `最近 ${asks.length} 条`;
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
  const apps = Array.isArray(focus.apps) ? focus.apps : [];
  const parts = minutesParts(focus.minutes);
  body.innerHTML = `
    <div class="panel-row"><span>专注时长</span><span>${escapeHtml(parts.value)} ${escapeHtml(parts.unit)}</span></div>
    <div class="panel-row"><span>窗口切换</span><span>${escapeHtml(focus.switches ?? 0)} 次</span></div>
    ${apps.length
      ? apps.map(([name, mins]) => `<div class="panel-row">
          <span>${escapeHtml(name)}</span><span>${Number(mins).toFixed(0)} 分钟</span></div>`).join("")
      : '<div class="hint" style="padding-top:10px">今天还没有开始录制。托盘里点「开始完整录制」才有专注数据。</div>'}`;
}

function renderCet6(items) {
  if (!items.length) return;
  const panel = document.getElementById("cet6-panel");
  const body = document.getElementById("cet6-body");
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
