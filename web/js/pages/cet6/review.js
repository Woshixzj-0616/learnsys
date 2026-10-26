// 六级训练内的到期错误卡复习：写作/翻译共用错题本与 FSRS，不另建队列。
import { api } from "../../api.js";
import { renderInto } from "../../markdown.js";
import { escapeHtml, toast } from "../../ui.js";

const RATING_LABELS = { 1: "忘了", 2: "模糊", 3: "记得", 4: "简单" };
const SOURCE_LABELS = { writing: "写作", translation: "翻译" };

let panel = null;
let ctx = null;
let items = [];
let index = 0;
let revealed = false;
let stats = { done: 0, forgot: 0 };

function current() {
  return items[index] || null;
}

function sourceLabel(item) {
  return SOURCE_LABELS[item?.source] || "错题";
}

async function load() {
  panel.innerHTML = '<div class="empty">正在读取到期错误卡…</div>';
  try {
    const data = await api.get("/api/cet6/train/errors?status=due&limit=200");
    items = Array.isArray(data.items) ? data.items : [];
    index = 0;
    revealed = false;
    stats = { done: 0, forgot: 0 };
    render();
  } catch (error) {
    panel.innerHTML = `<div class="empty"><strong>到期卡没读出来</strong>
      ${escapeHtml(error.message || "")}</div>`;
  }
}

function emptyHtml() {
  return `<div class="cet6-progress">
    <div class="cet6-progress-mark">✓</div>
    <h2>今天没有到期的错误卡</h2>
    <p>按记忆曲线，下一批会在到期后自动出现。</p>
    <div class="cet6-actions">
      <a class="btn btn-primary" href="#/cet6?tab=writing">去写作</a>
      <a class="btn" href="#/cet6?tab=translation">去翻译</a>
      <a class="btn btn-small" href="#/wrongbook">全部错题</a>
    </div>
  </div>`;
}

function doneHtml() {
  return `<div class="cet6-progress">
    <div class="cet6-progress-mark">✓</div>
    <h2>这一轮复习完了</h2>
    <p>复习 ${stats.done} 张 · 忘了或模糊 ${stats.forgot} 张</p>
    <p class="hint">忘了的卡会很快再出现；记得的会按记忆曲线拉长间隔。</p>
    <div class="cet6-actions">
      <button class="btn btn-primary" type="button" data-act="again">再查一遍到期</button>
      <a class="btn" href="#/cet6?tab=writing">去写作</a>
      <a class="btn" href="#/cet6?tab=translation">去翻译</a>
    </div>
  </div>`;
}

function cardHtml(item) {
  const answer = revealed ? `<div class="cet6-review-answer">
      <div class="cet6-review-line"><span>答案</span><div class="cet6-review-answer-text"></div></div>
      ${item.my_answer ? `<div class="cet6-review-line"><span>你当时写的</span>
        <p>${escapeHtml(item.my_answer)}</p></div>` : ""}
      ${item.note ? `<p class="hint">${escapeHtml(item.note)}</p>` : ""}
    </div>` : "";
  const actions = revealed
    ? Object.entries(RATING_LABELS).map(([rating, label]) => `
        <button class="btn ${rating === "3" ? "btn-primary" : ""}" type="button"
          data-act="rate" data-rating="${rating}">${label}</button>`).join("")
    : '<button class="btn btn-primary" type="button" data-act="reveal">显示答案</button>';
  const progress = Math.round((index) * 100 / Math.max(items.length, 1));
  return `<div class="cet6-review">
    <div class="cet6-review-top">
      <span class="cet6-kicker">到期复习 · 第 ${index + 1} / ${items.length} 张</span>
      <span class="cet6-chip">${escapeHtml(sourceLabel(item))}</span>
    </div>
    <div class="cet6-review-progress"><i style="width:${progress}%"></i></div>
    <article class="cet6-review-card">
      <p class="cet6-review-q">${escapeHtml(item.question || "")}</p>
      <div class="cet6-review-meta">
        ${item.tags ? `<span>${escapeHtml(item.tags)}</span>` : ""}
        ${item.next_review ? `<span>原定 ${escapeHtml(item.next_review)}</span>` : ""}
      </div>
      ${answer}
      <div class="cet6-actions">${actions}</div>
    </article>
    <p class="hint">先自己在心里改一遍，再显示答案；四档反馈决定下次什么时候出现。</p>
  </div>`;
}

function render() {
  const item = current();
  if (!item) {
    panel.innerHTML = emptyHtml();
    ctx.setSub("复习 · 今天没有到期的错误卡");
    return;
  }
  panel.innerHTML = cardHtml(item);
  const target = panel.querySelector(".cet6-review-answer-text");
  if (target) renderInto(target, item.answer || "（这道题还没有记录答案）");
  ctx.setSub(`复习 · 到期 ${items.length} 张 · 已完成 ${stats.done}`);
}

async function rate(rating, button) {
  const item = current();
  if (!item) return;
  if (button) button.disabled = true;
  try {
    const data = await api.post(`/api/review/wrong/${item.id}`, { rating });
    stats.done += 1;
    if (Number(rating) <= 2) stats.forgot += 1;
    toast(`${RATING_LABELS[rating]} · 下次 ${data.next_review || "已排期"}`, "ok");
    index += 1;
    revealed = false;
    if (index >= items.length) {
      panel.innerHTML = doneHtml();
      ctx.setSub(`复习 · 完成 ${stats.done} 张`);
    } else {
      render();
    }
  } catch (error) {
    if (button) button.disabled = false;
    toast(error.message || "复习没记上", "err");
  }
}

function onClick(event) {
  const target = event.target.closest("[data-act]");
  if (!target || !panel?.contains(target)) return;
  event.preventDefault();
  if (target.dataset.act === "reveal") {
    revealed = true;
    render();
  } else if (target.dataset.act === "rate") {
    rate(Number(target.dataset.rating || 3), target);
  } else if (target.dataset.act === "again") {
    load();
  }
}

export async function mount(context) {
  panel = context.panel;
  ctx = context.ctx;
  ctx.setActions('<a class="btn btn-small" href="#/wrongbook">全部错题</a>');
  panel.addEventListener("click", onClick);
  await load();
  return () => {
    panel?.removeEventListener("click", onClick);
    panel = null;
    ctx = null;
    items = [];
  };
}
