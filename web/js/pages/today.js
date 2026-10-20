// 今日：数字、时间线、待复习、快捷入口。数据全部来自 /api/today。
import { api } from "../api.js";
import { plain } from "../markdown.js";
import {
  charsParts, escapeHtml, minutesParts, timeOf, toast, todayLabel,
} from "../ui.js";

export async function mount(ctx) {
  ctx.setSub(todayLabel());
  ctx.setActions('<a class="btn btn-primary" href="#/ask">新问题</a>');

  const [today, conversations] = await Promise.all([
    api.get("/api/today"),
    api.get("/api/conversations?limit=8").catch(() => ({ items: [] })),
  ]);

  renderStats(today);
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
  const root = document.getElementById("today-stats");
  root.innerHTML = stats.map((stat) => `<div class="stat">
      <div class="stat-label">${escapeHtml(stat.label)}</div>
      <div class="stat-value">${escapeHtml(stat.value)}<small>${escapeHtml(stat.unit)}</small></div>
      <div class="stat-note">${escapeHtml(stat.note)}</div>
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
  body.querySelectorAll(".panel-row").forEach((row) => {
    row.style.cursor = "pointer";
    row.title = "P4 接入后可跳回这份试卷";
    row.addEventListener("click", () => toast("P4 接入后，点这里能直接回到这份试卷"));
  });
}
