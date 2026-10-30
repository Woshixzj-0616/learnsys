// 生活：订阅中心 + 今日卡片。新闻只读当天简报，生成/编辑/删除都走本地接口。
import { api } from "../api.js";
import { escapeHtml, relative, toast } from "../ui.js";
import { mount as mountItems, unmount as unmountItems } from "./life-items.js";

const KIND_LABEL = {
  news: "新闻", word: "每日一词", custom: "自定义",
  price: "价格（暂不支持）", stock: "股票（Tushare 日线）",
};
const CADENCE_LABEL = { daily: "每天", weekly: "每周" };

let subs = [];
let cards = [];
let itemStats = { open: 0, overdue: 0 };
let editingId = 0;
let nodes = {};

export async function mount(ctx) {
  ctx.setSub("按主题订阅新闻 / 每日一词 / 自定义内容；每天自动生成一张卡片，全部本地");
  nodes = {
    stats: ctx.root.querySelector("#life-stats"),
    cards: ctx.root.querySelector("#life-cards"),
    subs: ctx.root.querySelector("#life-subs"),
    form: ctx.root.querySelector("#life-form"),
    formTitle: ctx.root.querySelector("#life-form-title"),
    topic: ctx.root.querySelector("#lf-topic"),
    kind: ctx.root.querySelector("#lf-kind"),
    cadence: ctx.root.querySelector("#lf-cadence"),
    time: ctx.root.querySelector("#lf-time"),
    sources: ctx.root.querySelector("#lf-sources"),
    sourcesField: ctx.root.querySelector("#lf-sources-field"),
    sourcesLabel: ctx.root.querySelector("#lf-sources-label"),
    enabled: ctx.root.querySelector("#lf-enabled"),
    cancel: ctx.root.querySelector("#lf-cancel"),
    stockToken: ctx.root.querySelector("#lf-stock-token"),
    stockSave: ctx.root.querySelector("#lf-stock-save"),
    stockStatus: ctx.root.querySelector("#lf-stock-status"),
  };
  ctx.root.querySelector("#life-new").addEventListener("click", () => openForm());
  nodes.cancel.addEventListener("click", closeForm);
  nodes.form.addEventListener("submit", onSubmit);
  nodes.kind.addEventListener("change", syncSourcesField);
  nodes.cards.addEventListener("click", onCardsClick);
  nodes.subs.addEventListener("click", onSubsClick);
  nodes.stockSave.addEventListener("click", onSaveStockToken);
  await loadStockConfig();
  await mountItems(ctx, (counts) => {
    itemStats = counts || { open: 0, overdue: 0 };
    renderStats();
  });
  await load();
}

export function unmount() {
  unmountItems();
}

async function load() {
  await Promise.all([loadCards(), loadSubs()]);
  renderStats();
}

async function loadCards() {
  try {
    const data = await api.get("/api/life/cards?limit=50");
    cards = Array.isArray(data.items) ? data.items : [];
    renderCards();
  } catch (error) {
    nodes.cards.innerHTML = `<div class="empty"><strong>今日卡片没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

async function loadSubs() {
  try {
    const data = await api.get("/api/subscriptions");
    subs = Array.isArray(data.items) ? data.items : [];
    renderSubs();
  } catch (error) {
    nodes.subs.innerHTML = `<div class="empty"><strong>订阅没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function localToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
    + `-${String(now.getDate()).padStart(2, "0")}`;
}

function renderStats() {
  const today = localToday();
  const todayCards = cards.filter((card) => card.day === today);
  nodes.stats.innerHTML = [
    ["待办", Number(itemStats.open || 0)],
    ["今日卡片", todayCards.length],
    ["未读", cards.filter((card) => !card.read).length],
  ].map(([label, value]) => `
    <div class="review-chip"><span>${escapeHtml(label)}</span><strong>${value}</strong></div>
  `).join("");
}

function safeUrl(url) {
  const text = String(url || "").trim();
  return /^https?:\/\//i.test(text) ? text : "";
}

function renderCards() {
  if (!cards.length) {
    nodes.cards.innerHTML = `<div class="empty"><strong>今天还没有卡片</strong>
      到点后会自动生成；也可以在上面的订阅点「现在生成」。新闻订阅要等当天简报先生成。</div>`;
    return;
  }
  nodes.cards.innerHTML = cards.map((card) => {
    const content = card.content || {};
    const items = Array.isArray(content.items) ? content.items : [];
    const links = items.map((item) => {
      const url = safeUrl(item.url);
      const title = item.title_zh || item.title || "（无标题）";
      const label = escapeHtml(title);
      return `<li>${url
        ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${label}</a>`
        : label}${item.source ? ` <span class="life-hint">${escapeHtml(item.source)}</span>` : ""}</li>`;
    }).join("");
    return `
      <article class="life-card${card.read ? " is-read" : ""}" data-card-id="${card.id}">
        <div class="life-card-head">
          <span class="life-card-topic">${escapeHtml(card.title)}</span>
          <span class="life-card-meta">${escapeHtml(card.day)} ·
            ${escapeHtml(KIND_LABEL[content.kind] || content.kind || "卡片")}</span>
        </div>
        <p>${escapeHtml(content.summary || "（没有摘要）")}</p>
        ${links ? `<ul>${links}</ul>` : ""}
        <div class="life-card-actions">
          <button class="btn btn-quiet" type="button" data-read="${card.id}">
            ${card.read ? "标为未读" : "标记已读"}</button>
        </div>
      </article>`;
  }).join("");
}

function renderSubs() {
  if (!subs.length) {
    nodes.subs.innerHTML = `<div class="empty"><strong>还没有订阅</strong>
      点右上角「新建订阅」。新闻订阅会筛选当天简报；每日一词 / 自定义各调用一次模型。</div>`;
    return;
  }
  nodes.subs.innerHTML = subs.map((sub) => {
    const kind = KIND_LABEL[sub.kind] || sub.kind;
    const last = sub.last_run ? relative(sub.last_run) : "从未运行";
    return `
      <div class="life-sub${sub.enabled ? "" : " is-off"}" data-sub-id="${sub.id}">
        <div class="life-sub-head">
          <strong>${escapeHtml(sub.topic)}</strong>
          <span class="life-badge">${escapeHtml(kind)}</span>
          ${sub.enabled ? "" : '<span class="life-badge">已停用</span>'}
        </div>
        <div class="life-sub-meta">
          ${escapeHtml(CADENCE_LABEL[sub.cadence] || sub.cadence)} ${escapeHtml(sub.at_time)}
          · 上次运行：${escapeHtml(last)}
        </div>
        <div class="life-sub-actions">
          <button class="btn btn-primary" type="button" data-run="${sub.id}">现在生成</button>
          <button class="btn btn-quiet" type="button" data-edit="${sub.id}">编辑</button>
          <button class="btn btn-quiet" type="button" data-del="${sub.id}">删除</button>
        </div>
      </div>`;
  }).join("");
}

function syncSourcesField() {
  const kind = nodes.kind.value;
  const visible = kind === "news" || kind === "stock";
  nodes.sourcesField.hidden = !visible;
  if (kind === "stock") {
    nodes.sourcesLabel.textContent =
      "股票/指数代码（逗号分隔；指数如 000001.SH 上证、399001.SZ 深证；最多 5 个）";
    nodes.sources.placeholder = "600519.SH, 000001.SH";
  } else {
    nodes.sourcesLabel.textContent =
      "来源（可选，逗号分隔；填来源名或类目，如 量子位, ai）";
    nodes.sources.placeholder = "量子位, IT之家";
  }
}

async function loadStockConfig() {
  try {
    const data = await api.get("/api/life/stock/config");
    renderStockStatus(data);
  } catch (error) {
    nodes.stockStatus.textContent = "股票配置没读出来";
  }
}

function renderStockStatus(data) {
  const configured = Boolean(data && data.configured);
  nodes.stockStatus.textContent = configured
    ? `已配置（尾号 ${data.token_tail || "****"}）`
    : "未配置：股票卡片会提示先填 token";
}

async function onSaveStockToken() {
  const token = nodes.stockToken.value.trim();
  nodes.stockSave.disabled = true;
  try {
    const data = await api.post("/api/life/stock/config", { token });
    nodes.stockToken.value = "";
    renderStockStatus(data);
    toast(token ? "股票 token 已保存" : "已清除股票 token");
  } catch (error) {
    toast(error.message || error, "err");
  } finally {
    nodes.stockSave.disabled = false;
  }
}

function openForm(sub = null) {
  editingId = sub ? sub.id : 0;
  nodes.formTitle.textContent = sub ? "编辑订阅" : "新建订阅";
  nodes.topic.value = sub ? sub.topic : "";
  nodes.kind.value = sub ? sub.kind : "news";
  nodes.cadence.value = sub ? sub.cadence : "daily";
  nodes.time.value = sub ? sub.at_time : "07:30";
  nodes.sources.value = sub ? (sub.sources || []).join(", ") : "";
  nodes.enabled.checked = sub ? Boolean(sub.enabled) : true;
  syncSourcesField();
  nodes.form.hidden = false;
  nodes.topic.focus();
}

function closeForm() {
  nodes.form.hidden = true;
  editingId = 0;
}

function formPayload() {
  const codes = nodes.kind.value === "stock";
  const sources = nodes.sources.value.split(/[,，\s]+/)
    .map((item) => (codes ? item.trim().toUpperCase() : item.trim()))
    .filter(Boolean);
  return {
    topic: nodes.topic.value.trim(),
    kind: nodes.kind.value,
    cadence: nodes.cadence.value,
    at_time: nodes.time.value || "07:30",
    sources,
    enabled: nodes.enabled.checked,
  };
}

async function onSubmit(event) {
  event.preventDefault();
  const payload = formPayload();
  if (!payload.topic) {
    toast("主题不能为空", "err");
    return;
  }
  try {
    if (editingId) await api.patch(`/api/subscriptions/${editingId}`, payload);
    else await api.post("/api/subscriptions", payload);
    toast("已保存");
    closeForm();
    await load();
  } catch (error) {
    toast(error.message || error, "err");
  }
}

async function onCardsClick(event) {
  const button = event.target.closest("[data-read]");
  if (!button) return;
  const card = cards.find((item) => String(item.id) === button.dataset.read);
  if (!card) return;
  button.disabled = true;
  try {
    await api.post(`/api/life/cards/${card.id}/read`, { read: !card.read });
    await loadCards();
    renderStats();
  } catch (error) {
    toast(error.message || error, "err");
  } finally {
    button.disabled = false;
  }
}

async function onSubsClick(event) {
  const run = event.target.closest("[data-run]");
  if (run) {
    run.disabled = true;
    run.textContent = "生成中…";
    try {
      const body = await api.post(`/api/subscriptions/${run.dataset.run}/run`);
      toast(body.card ? "卡片已生成" : "已处理");
      await load();
    } catch (error) {
      toast(error.message || error, "err");
    } finally {
      run.disabled = false;
      run.textContent = "现在生成";
    }
    return;
  }
  const edit = event.target.closest("[data-edit]");
  if (edit) {
    const sub = subs.find((item) => String(item.id) === edit.dataset.edit);
    if (sub) openForm(sub);
    return;
  }
  const del = event.target.closest("[data-del]");
  if (del) {
    const sub = subs.find((item) => String(item.id) === del.dataset.del);
    if (!sub) return;
    if (!confirm(`删除订阅「${sub.topic}」？已生成的卡片会保留。`)) return;
    try {
      await api.del(`/api/subscriptions/${sub.id}`);
      toast("已删除");
      await load();
    } catch (error) {
      toast(error.message || error, "err");
    }
  }
}
