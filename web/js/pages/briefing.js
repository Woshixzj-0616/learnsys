// 每日简报：按天回看时政与科技前沿，条目可已读/收藏。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

const STATUS_LABELS = {
  missing: "还没生成", scheduled: "定时生成", pending: "排队中",
  running: "生成中", ready: "已生成", partial: "部分完成", failed: "生成失败",
};
const CATEGORY_ORDER = ["all", "politics", "world", "ai", "hardware",
                        "internet", "health", "science", "energy", "other"];

let nodes = {};
let state = { day: "", data: null, filter: "all", timer: null, polls: 0 };

function todayText() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function shiftDay(day, delta) {
  const parsed = new Date(`${day}T00:00:00`);
  parsed.setDate(parsed.getDate() + delta);
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(parsed.getDate()).padStart(2, "0")}`;
}

function clearTimer() {
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
}

function itemById(id) {
  return (state.data?.items || []).find((item) => Number(item.id) === Number(id)) || null;
}

export async function mount(ctx) {
  ctx.setSub("时政与科技前沿，每天 3 分钟；摘要由模型生成，以原文为准");
  state = { day: todayText(), data: null, filter: "all", timer: null, polls: 0 };
  nodes = {
    status: ctx.root.querySelector("#briefing-status"),
    count: ctx.root.querySelector("#briefing-count"),
    sources: ctx.root.querySelector("#briefing-sources"),
    intro: ctx.root.querySelector("#briefing-intro"),
    list: ctx.root.querySelector("#briefing-list"),
    filters: ctx.root.querySelector("#briefing-filters"),
    day: ctx.root.querySelector("#briefing-day"),
    history: ctx.root.querySelector("#briefing-history"),
    prev: ctx.root.querySelector("#briefing-prev"),
    next: ctx.root.querySelector("#briefing-next"),
    regenerate: ctx.root.querySelector("#briefing-regenerate"),
    readall: ctx.root.querySelector("#briefing-readall"),
  };
  nodes.day.value = state.day;
  nodes.day.max = todayText();
  bind();
  await loadDays();
  await load();
}

export function unmount() {
  clearTimer();
  nodes = {};
}

function bind() {
  nodes.prev.addEventListener("click", () => {
    state.day = shiftDay(state.day, -1);
    state.polls = 0;
    syncDay();
    load();
  });
  nodes.next.addEventListener("click", () => {
    state.day = shiftDay(state.day, 1);
    state.polls = 0;
    syncDay();
    load();
  });
  nodes.day.addEventListener("change", () => {
    if (!nodes.day.value) return;
    state.day = nodes.day.value;
    state.polls = 0;
    load();
  });
  nodes.history.addEventListener("change", () => {
    if (!nodes.history.value) return;
    state.day = nodes.history.value;
    state.polls = 0;
    syncDay();
    load();
  });
  nodes.regenerate.addEventListener("click", regenerate);
  nodes.readall.addEventListener("click", readAll);
  nodes.filters.addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter || "all";
    render();
  });
  nodes.list.addEventListener("click", async (event) => {
    const star = event.target.closest('[data-act="star"]');
    if (star) {
      const item = itemById(star.closest("[data-id]")?.dataset.id);
      if (!item) return;
      try {
        const result = await api.patch(`/api/briefing/items/${item.id}`,
                                       { starred: !item.starred });
        item.starred = Boolean(result.item?.starred);
        star.textContent = item.starred ? "★" : "☆";
        star.setAttribute("aria-pressed", String(item.starred));
        toast(item.starred ? "已收藏" : "已取消收藏");
      } catch (error) {
        toast(error.message, "error");
      }
      return;
    }
    const link = event.target.closest('[data-act="open"]');
    if (!link) return;
    const item = itemById(link.closest("[data-id]")?.dataset.id);
    if (!item || item.read) return;
    item.read = true;
    link.closest(".briefing-item")?.classList.add("read");
    api.patch(`/api/briefing/items/${item.id}`, { read: true }).catch(() => {});
  });
}

async function loadDays() {
  try {
    const data = await api.get("/api/briefing/days?limit=30");
    const days = Array.isArray(data.items) ? data.items : [];
    const known = new Set(days.map((row) => row.day));
    const options = days.map((row) => {
      const label = `${row.day} · ${STATUS_LABELS[row.status] || row.status} · ${row.item_count || 0} 条`;
      return `<option value="${escapeHtml(row.day)}">${escapeHtml(label)}</option>`;
    });
    if (!known.has(state.day)) {
      options.unshift(`<option value="${state.day}">${state.day} · 今天</option>`);
    }
    nodes.history.innerHTML = options.join("");
    nodes.history.value = state.day;
  } catch {
    // 历史读不到不阻塞当天简报
  }
}

function syncDay() {
  nodes.day.value = state.day;
  nodes.day.max = todayText();
  nodes.next.disabled = state.day >= todayText();
  if (nodes.history) {
    const has = [...nodes.history.options].some((option) => option.value === state.day);
    if (!has) {
      const option = document.createElement("option");
      option.value = state.day;
      option.textContent = state.day;
      nodes.history.prepend(option);
    }
    nodes.history.value = state.day;
  }
}

async function load() {
  clearTimer();
  syncDay();
  try {
    state.data = await api.get(`/api/briefing?day=${encodeURIComponent(state.day)}`);
    render();
    if (["pending", "running"].includes(state.data.status) && state.polls < 12) {
      state.polls += 1;
      state.timer = setTimeout(load, 5000);
    }
  } catch (error) {
    state.data = null;
    nodes.status.textContent = "读取失败";
    nodes.list.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    toast(error.message, "error");
  }
}

function render() {
  const data = state.data;
  if (!data) return;
  const status = data.status || "missing";
  const label = STATUS_LABELS[status] || status;
  const suffix = status === "scheduled" && data.generate_at ? ` · ${data.generate_at}` : "";
  nodes.status.textContent = label + suffix;
  nodes.status.dataset.state = status;
  const items = Array.isArray(data.items) ? data.items : [];
  const readCount = items.filter((item) => item.read).length;
  nodes.count.textContent = items.length ? `${items.length} 条 · 已读 ${readCount}` : "";
  nodes.sources.textContent = data.source_total
    ? `源 ${data.source_ok}/${data.source_total} 可用` : "";
  nodes.regenerate.disabled = ["pending", "running"].includes(status);
  nodes.readall.disabled = !items.length;

  const intro = String(data.intro || "").trim();
  const error = String(data.error || "").trim();
  const introParts = [];
  if (intro) introParts.push(`<p>${escapeHtml(intro)}</p>`);
  if (error) introParts.push(`<p class="feed-note">${escapeHtml(error)}</p>`);
  nodes.intro.hidden = !introParts.length;
  nodes.intro.innerHTML = introParts.join("");

  if (state.filter !== "all" && !items.some((item) => item.category === state.filter)) {
    state.filter = "all";
  }
  renderFilters(items);
  renderList(items, status, error);
}

function renderFilters(items) {
  const counts = {};
  items.forEach((item) => { counts[item.category] = (counts[item.category] || 0) + 1; });
  const labels = { all: "全部" };
  items.forEach((item) => { labels[item.category] = item.category_label || item.category; });
  nodes.filters.innerHTML = CATEGORY_ORDER
    .filter((key) => key === "all" || counts[key])
    .map((key) => `<button class="chip${state.filter === key ? " active" : ""}" type="button"
      data-filter="${escapeHtml(key)}">${escapeHtml(labels[key] || key)}
      ${key === "all" ? items.length : counts[key]}</button>`).join("");
}

function emptyText(status, error) {
  if (status === "missing") {
    return `今天的简报还没生成。点右上角「重新生成」，或等每天定时生成。`;
  }
  if (status === "scheduled") {
    return `每天定时生成；现在也可以点右上角「重新生成」。`;
  }
  if (["pending", "running"].includes(status)) {
    return "正在抓取信息源并写摘要，通常 1~2 分钟。";
  }
  if (status === "failed") {
    return `生成失败：${error || "请稍后重试"}`;
  }
  return "今天这个分类没有条目。";
}

function renderList(items, status, error) {
  const shown = state.filter === "all"
    ? items : items.filter((item) => item.category === state.filter);
  if (!shown.length) {
    nodes.list.innerHTML = `<div class="empty">${escapeHtml(emptyText(status, error))}</div>`;
    return;
  }
  nodes.list.innerHTML = shown.map((item) => {
    const title = item.title_zh || item.title || "";
    const note = item.summary_source === "feed"
      ? '<span class="feed-note">原文摘要</span>' : "<span>模型摘要</span>";
    return `<article class="briefing-item${item.read ? " read" : ""}" data-id="${item.id}">
      <div class="briefing-item-top">
        <span class="briefing-tag">${escapeHtml(item.category_label || "其他")}</span>
        <time class="briefing-time">${escapeHtml(item.published_at || "")}</time>
        <button class="briefing-star" type="button" data-act="star"
          aria-pressed="${item.starred ? "true" : "false"}"
          aria-label="${item.starred ? "取消收藏" : "收藏"}">${item.starred ? "★" : "☆"}</button>
      </div>
      <h3><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener"
        data-act="open">${escapeHtml(title)}</a></h3>
      <p>${escapeHtml(item.summary || "")}</p>
      <div class="briefing-item-foot">
        <span>${escapeHtml(item.source || "")}</span>${note}
      </div>
    </article>`;
  }).join("");
}

async function regenerate() {
  try {
    await api.post("/api/briefing/generate", { day: state.day, force: true });
    state.polls = 0;
    toast("已开始生成，通常 1~2 分钟");
    await load();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function readAll() {
  if (!state.data?.items?.length) return;
  try {
    await api.post("/api/briefing/read-all", { day: state.day });
    await load();
    toast("已全部标记为已读");
  } catch (error) {
    toast(error.message, "error");
  }
}
