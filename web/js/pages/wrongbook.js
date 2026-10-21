// 错题本：待复习 / 全部 / 已掌握；展开看答案，标掌握、删除、导出 Anki。
import { api, download } from "../api.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, toast } from "../ui.js";

const SOURCE_LABEL = { ask: "问答收藏", quiz: "测验错题", manual: "手动收录", cet6: "六级断点" };
const STAGE_TEXT = ["还没复习", "复习过 1 轮", "复习过 2 轮", "练完 3 轮"];

let status = "due";
let source = "";
let materialFilter = 0;
let items = [];
let counts = { all: 0, due: 0, mastered: 0 };
let materialFacets = [];
let nodes = {};

export async function mount(ctx) {
  ctx.setSub("答错的、收藏的，都在这本里；按 1 / 3 / 7 天复习");
  ctx.setActions('<a class="btn" href="#/quiz">去测验</a>');
  nodes = {
    list: ctx.root.querySelector("#wrong-list"),
    stats: ctx.root.querySelector("#wrong-stats"),
    tabs: Array.from(ctx.root.querySelectorAll(".wrong-tab")),
    source: ctx.root.querySelector("#wrong-source"),
    material: ctx.root.querySelector("#wrong-material"),
    export: ctx.root.querySelector("#wrong-export"),
  };
  nodes.tabs.forEach((tab) => tab.addEventListener("click", () => {
    status = tab.dataset.status || "due";
    nodes.tabs.forEach((item) => item.classList.toggle("active", item === tab));
    load();
  }));
  nodes.source.addEventListener("change", () => {
    source = nodes.source.value;
    load();
  });
  nodes.material.addEventListener("change", () => {
    materialFilter = Number(nodes.material.value || 0);
    load();
  });
  nodes.export.addEventListener("click", exportCsv);
  nodes.list.addEventListener("click", onListClick);
  await load();
}

async function load() {
  try {
    const query = new URLSearchParams({ status, source, limit: "500" });
    if (materialFilter) query.set("material_id", String(materialFilter));
    const data = await api.get(`/api/wrongbook?${query}`);
    items = Array.isArray(data.items) ? data.items : [];
    counts = data.counts || counts;
    materialFacets = Array.isArray(data.materials) ? data.materials : [];
    renderStats();
    renderMaterials();
    renderList();
  } catch (error) {
    nodes.list.innerHTML = `<div class="empty"><strong>错题本没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function renderStats() {
  nodes.stats.innerHTML = [
    ["待复习", counts.due ?? 0, "due"],
    ["全部", counts.all ?? 0, "all"],
    ["已掌握", counts.mastered ?? 0, "mastered"],
  ].map(([label, value, key]) => `
    <div class="review-chip wrong-stat ${status === key ? "active" : ""}">
      <span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>
    </div>
  `).join("");
}

function renderMaterials() {
  const options = ['<option value="0">全部资料</option>'];
  for (const facet of materialFacets) {
    options.push(`<option value="${facet.material_id}">${escapeHtml(facet.title)}（${facet.count}）</option>`);
  }
  nodes.material.innerHTML = options.join("");
  if (materialFilter && !materialFacets.some((one) => one.material_id === materialFilter)) {
    materialFilter = 0;
  }
  nodes.material.value = String(materialFilter || 0);
}

function dayOf(stamp) {
  return String(stamp || "").slice(0, 10);
}

function daysOverdue(item) {
  const due = dayOf(item.next_review);
  if (!due) return 0;
  const today = new Date();
  const todayText = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const diff = Math.floor((new Date(todayText) - new Date(due)) / 86400000);
  return diff > 0 ? diff : 0;
}

function dueBadge(item) {
  if (item.mastered) return '<span class="wrong-badge mastered">已掌握</span>';
  const overdue = daysOverdue(item);
  if (overdue > 0) return `<span class="wrong-badge due">逾期 ${overdue} 天</span>`;
  if (item.next_review && dayOf(item.next_review) <= todayText()) {
    return '<span class="wrong-badge due">今天到期</span>';
  }
  return "";
}

function todayText() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function emptyText() {
  if (source) return "这个来源下还没有题。";
  if (status === "due") return "今天没有到期的错题 —— 去「全部」看看，或者去测验攒几道。";
  if (status === "mastered") return "还没有标记为掌握的题。";
  return "错题本还是空的 —— 测验答错会自动收进来，问答也能收藏。";
}

function renderList() {
  if (!items.length) {
    nodes.list.innerHTML = `<div class="empty"><strong>暂时空着</strong>${escapeHtml(emptyText())}</div>`;
    return;
  }
  nodes.list.innerHTML = items.map((item) => {
    const stage = item.mastered ? "已掌握" : (STAGE_TEXT[item.review_stage] || "还没复习");
    const next = item.next_review ? `下次复习 ${item.next_review}` : "";
    return `
      <article class="wrong-card ${dueBadge(item) ? "is-due" : ""}" data-id="${item.id}">
        <button class="wrong-card-head" type="button" aria-expanded="false">
          <span class="wrong-source ${escapeHtml(item.source)}">${escapeHtml(SOURCE_LABEL[item.source] || "错题")}</span>
          <span class="wrong-question">${escapeHtml(item.question)}</span>
          <span class="wrong-card-side">${dueBadge(item)}
            <span class="hint">${escapeHtml(dayOf(item.ts))} 收录</span>
          </span>
        </button>
        <div class="wrong-card-body" hidden>
          <div class="wrong-block">
            <h4>正确答案</h4>
            <div class="wrong-answer"></div>
          </div>
          ${item.my_answer ? `<div class="wrong-block">
            <h4>我当时答的</h4>
            <pre class="wrong-mine">${escapeHtml(item.my_answer)}</pre>
          </div>` : ""}
          <div class="wrong-meta">
            ${item.material_title ? `<span>资料：${escapeHtml(item.material_title)}</span>` : ""}
            ${item.tags ? `<span>知识点：${escapeHtml(item.tags)}</span>` : ""}
            <span>${escapeHtml(stage)}${next ? ` · ${escapeHtml(next)}` : ""}</span>
          </div>
          <div class="wrong-actions">
            <button class="btn btn-primary" type="button" data-act="remember">记住了</button>
            <button class="btn" type="button" data-act="forgot">没记住</button>
            <button class="btn btn-quiet" type="button" data-act="master">${item.mastered ? "取消掌握" : "标记掌握"}</button>
            <button class="btn btn-danger" type="button" data-act="delete">删除</button>
          </div>
        </div>
      </article>`;
  }).join("");
  nodes.list.querySelectorAll(".wrong-answer").forEach((el) => {
    const id = Number(el.closest(".wrong-card")?.dataset.id || 0);
    const item = items.find((one) => one.id === id);
    renderInto(el, item?.answer || "（这道题还没有记录答案）");
  });
}

function onListClick(event) {
  const card = event.target.closest(".wrong-card");
  if (!card) return;
  const head = event.target.closest(".wrong-card-head");
  if (head) {
    const body = card.querySelector(".wrong-card-body");
    const open = body.hidden;
    body.hidden = !open;
    head.setAttribute("aria-expanded", String(open));
    return;
  }
  const button = event.target.closest("[data-act]");
  if (!button) return;
  const id = Number(card.dataset.id || 0);
  const item = items.find((one) => one.id === id);
  if (!item) return;
  act(button.dataset.act, item, button);
}

async function act(action, item, button) {
  button.disabled = true;
  try {
    if (action === "remember" || action === "forgot") {
      const data = await api.post(`/api/wrongbook/${item.id}/review`, { result: action });
      const next = data.item?.next_review;
      toast(action === "remember"
        ? (next ? `记下了，下次 ${next} 再复习` : "这道题练完 3 轮，已标记掌握")
        : "没关系，明天再来一次", "ok");
    } else if (action === "master") {
      await api.post(`/api/wrongbook/${item.id}/master`, { mastered: !item.mastered });
      toast(item.mastered ? "已取消掌握" : "已标记掌握", "ok");
    } else if (action === "delete") {
      if (!window.confirm("从错题本删掉这道题？删了不会影响问答和测验记录。")) {
        button.disabled = false;
        return;
      }
      await api.del(`/api/wrongbook/${item.id}`);
      toast("已从错题本删除", "ok");
    }
    await load();
  } catch (error) {
    button.disabled = false;
    toast(error.message || "操作没成功", "err");
  }
}

async function exportCsv() {
  nodes.export.disabled = true;
  try {
    const now = new Date();
    const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
    await download("/api/wrongbook/export", `错题本_${stamp}.csv`);
    toast("已导出 —— 在 Anki 里「文件 → 导入」选这个 CSV", "ok");
  } catch (error) {
    toast(error.message || "导出失败", "err");
  } finally {
    nodes.export.disabled = false;
  }
}
