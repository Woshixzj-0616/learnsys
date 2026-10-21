// 生词本：统一词表 + FSRS 复习（列表、搜索、手动加词、四档复习、导出）。
import { api, download } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

const RATING_LABELS = { 1: "忘了", 2: "模糊", 3: "记得", 4: "简单" };
const STATE_LABEL = { new: "新词", learning: "学习中", review: "复习中" };

let items = [];
let query = "";
let queue = [];
let index = 0;
let revealed = false;
let nodes = {};
let searchTimer = null;
let meaningTimers = new Map();

function todayText() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function dueBadge(item) {
  const due = String(item.next_review || "");
  if (!due) return "";
  if (due <= todayText()) return '<span class="wrong-badge due">今天到期</span>';
  return `<span class="wrong-badge">${escapeHtml(due)}</span>`;
}

export async function mount(ctx) {
  ctx.setSub("划词收藏与手动添加的词统一进库；按记忆曲线安排复习");
  ctx.setActions('<a class="btn" href="#/cet6">去六级精听</a>');
  items = [];
  query = "";
  queue = [];
  index = 0;
  revealed = false;
  nodes = {
    list: ctx.root.querySelector("#vocab-list"),
    stats: ctx.root.querySelector("#vocab-stats"),
    count: ctx.root.querySelector("#vocab-count"),
    search: ctx.root.querySelector("#vocab-search"),
    newWord: ctx.root.querySelector("#vocab-new-word"),
    newMeaning: ctx.root.querySelector("#vocab-new-meaning"),
    add: ctx.root.querySelector("#vocab-add"),
    export: ctx.root.querySelector("#vocab-export"),
    start: ctx.root.querySelector("#vocab-review-start"),
    review: ctx.root.querySelector("#vocab-review-panel"),
    reviewBody: ctx.root.querySelector("#vocab-review-body"),
    reviewProgress: ctx.root.querySelector("#vocab-review-progress"),
    reviewClose: ctx.root.querySelector("#vocab-review-close"),
  };

  nodes.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      query = nodes.search.value.trim();
      load();
    }, 220);
  });
  nodes.add.addEventListener("click", addWord);
  nodes.newWord.addEventListener("keydown", (event) => {
    if (event.key === "Enter") addWord();
  });
  nodes.export.addEventListener("click", exportCsv);
  nodes.start.addEventListener("click", startReview);
  nodes.reviewClose.addEventListener("click", closeReview);
  nodes.list.addEventListener("input", onMeaningEdit);
  nodes.list.addEventListener("click", onListClick);
  nodes.reviewBody.addEventListener("click", onReviewClick);
  await load();
}

async function load() {
  try {
    const listPath = `/api/vocab?limit=300${query ? `&query=${encodeURIComponent(query)}` : ""}`;
    const [stats, list] = await Promise.all([
      api.get("/api/review/stats?item_type=vocab"),
      api.get(listPath),
    ]);
    items = Array.isArray(list.items) ? list.items : [];
    nodes.count.textContent = `${list.count ?? items.length} 个词`;
    renderStats(stats || {});
    renderList();
  } catch (error) {
    nodes.list.innerHTML = `<div class="empty"><strong>生词本没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function renderStats(stats) {
  const chips = [
    ["待复习", stats.due ?? 0],
    ["新词", stats.new ?? 0],
    ["总数", stats.total ?? 0],
  ];
  nodes.stats.innerHTML = chips.map(([label, value]) =>
    `<div class="review-chip"><span>${label}</span><strong>${escapeHtml(String(value))}</strong></div>`
  ).join("");
}

function renderList() {
  if (!items.length) {
    nodes.list.innerHTML = `<div class="empty"><strong>${query ? "没有匹配的词" : "生词本还是空的"}</strong>
      ${query ? "换个关键词试试。" : "在六级精听里划词翻译后点「＋生词」，或在上面的输入框手动添加。"}</div>`;
    return;
  }
  nodes.list.innerHTML = items.map((item) => {
    const reps = Number(item.review_reps || 0);
    const lapses = Number(item.review_lapses || 0);
    const state = STATE_LABEL[item.review_state] || "新词";
    const meta = [`${state}`, item.next_review ? `下次 ${item.next_review}` : ""]
      .concat(reps ? [`复习 ${reps} 次${lapses ? ` · 遗忘 ${lapses} 次` : ""}`] : [])
      .filter(Boolean).map((text) => `<span>${escapeHtml(text)}</span>`).join("");
    return `
      <article class="wrong-card" data-id="${item.id}">
        <div class="wrong-card-head" style="cursor:default">
          <span class="wrong-source">生词</span>
          <span class="wrong-question">
            <span class="vocab-word">${escapeHtml(item.word)}</span>
            ${item.phonetic ? `<span class="vocab-phonetic">${escapeHtml(item.phonetic)}</span>` : ""}
            ${item.context ? `<div class="vocab-context">${escapeHtml(item.context)}</div>` : ""}
          </span>
          <span class="wrong-card-side">${dueBadge(item)}
            <span class="hint">${escapeHtml(item.paper_title || "")}</span>
          </span>
        </div>
        <div class="wrong-card-body">
          <input class="input vocab-meaning" type="text" data-meaning="${item.id}"
                 value="${escapeHtml(item.meaning || "")}" placeholder="释义 / 备注">
          <div class="wrong-meta">${meta}</div>
          <div class="wrong-actions">
            <button class="btn btn-danger" type="button" data-del="${item.id}">删除</button>
          </div>
        </div>
      </article>`;
  }).join("");
}

async function addWord() {
  const word = nodes.newWord.value.trim();
  const meaning = nodes.newMeaning.value.trim();
  if (!word) {
    toast("先填一个单词");
    nodes.newWord.focus();
    return;
  }
  nodes.add.disabled = true;
  try {
    const data = await api.post("/api/vocab", { word, meaning, source: "manual" });
    toast(data.created ? `已加入：${word}` : `「${word}」已经在生词本里了`, "ok");
    nodes.newWord.value = "";
    nodes.newMeaning.value = "";
    await load();
  } catch (error) {
    toast(error.message || "添加失败", "err");
  } finally {
    nodes.add.disabled = false;
  }
}

function onMeaningEdit(event) {
  const input = event.target.closest("input[data-meaning]");
  if (!input) return;
  const id = Number(input.dataset.meaning || 0);
  clearTimeout(meaningTimers.get(id));
  meaningTimers.set(id, setTimeout(async () => {
    try {
      await api.patch(`/api/vocab/${id}`, { meaning: input.value });
      const item = items.find((one) => one.id === id);
      if (item) item.meaning = input.value;
    } catch (error) {
      toast(error.message || "释义没保存上", "err");
    }
  }, 500));
}

async function onListClick(event) {
  const button = event.target.closest("button[data-del]");
  if (!button) return;
  const id = Number(button.dataset.del || 0);
  if (!window.confirm("从生词本删掉这个词？")) return;
  button.disabled = true;
  try {
    await api.del(`/api/vocab/${id}`);
    toast("已删除", "ok");
    await load();
  } catch (error) {
    button.disabled = false;
    toast(error.message || "删除失败", "err");
  }
}

async function startReview() {
  nodes.start.disabled = true;
  try {
    const data = await api.get("/api/review/queue?item_type=vocab&limit=100");
    queue = Array.isArray(data.items) ? data.items : [];
    index = 0;
    revealed = false;
    if (!queue.length) {
      toast("今天没有到期的生词；新词明天才会出现", "ok");
      return;
    }
    nodes.review.hidden = false;
    renderReview();
  } catch (error) {
    toast(error.message || "复习队列没读出来", "err");
  } finally {
    nodes.start.disabled = false;
  }
}

function renderReview() {
  if (index >= queue.length) {
    nodes.review.hidden = true;
    toast(`这一轮复习完成，共 ${queue.length} 张`, "ok");
    load();
    return;
  }
  const card = queue[index];
  nodes.reviewProgress.textContent = `第 ${index + 1} / ${queue.length} 张`;
  const phonetic = card.paper_title ? `<span class="vocab-phonetic">${escapeHtml(card.paper_title)}</span>` : "";
  nodes.reviewBody.innerHTML = `
    <div class="vocab-review-card">
      <div class="vocab-review-word">${escapeHtml(card.word || "")}</div>
      ${phonetic}
      ${card.context ? `<div class="vocab-review-context">${escapeHtml(card.context)}</div>` : ""}
      <div class="vocab-review-reveal">
        <button class="btn btn-primary" type="button" id="vocab-show">显示释义</button>
      </div>
      <div class="vocab-review-answer" ${revealed ? "" : "hidden"}>
        <div class="vocab-review-meaning">${escapeHtml(card.meaning || "（还没有释义）")}</div>
        <div class="wrong-actions vocab-review-actions">
          ${[1, 2, 3, 4].map((rating) => `<button class="btn ${rating === 3 ? "btn-primary" : ""}"
            type="button" data-rating="${rating}">${RATING_LABELS[rating]}</button>`).join("")}
        </div>
      </div>
    </div>`;
}

async function onReviewClick(event) {
  if (event.target.closest("#vocab-show")) {
    revealed = true;
    renderReview();
    return;
  }
  const button = event.target.closest("button[data-rating]");
  if (!button) return;
  const card = queue[index];
  if (!card) return;
  button.disabled = true;
  try {
    const rating = Number(button.dataset.rating || 3);
    const data = await api.post(`/api/review/vocab/${card.item_id}`, { rating });
    toast(`${RATING_LABELS[rating]} · 下次 ${data.next_review}（${data.scheduled_days} 天后）`, "ok");
    index += 1;
    revealed = false;
    renderReview();
  } catch (error) {
    button.disabled = false;
    toast(error.message || "复习没记上", "err");
  }
}

function closeReview() {
  nodes.review.hidden = true;
  load();
}

async function exportCsv() {
  nodes.export.disabled = true;
  try {
    const now = new Date();
    const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
    await download("/api/vocab/export.csv", `生词本_${stamp}.csv`);
    toast("已导出 CSV", "ok");
  } catch (error) {
    toast(error.message || "导出失败", "err");
  } finally {
    nodes.export.disabled = false;
  }
}
