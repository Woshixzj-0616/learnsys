// 英语复习：句子 / 单词短语两个 tab，共用一套 FSRS 队列。
// 交互原则：先自己答或译，再看参考；错题本只做浏览历史，不再承担复习。
import { api } from "../api.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, toast } from "../ui.js";

const RATING_LABELS = { 1: "忘了", 2: "模糊", 3: "记得", 4: "简单" };
const SOURCE_LABELS = {
  writing: "写作", translation: "翻译", sentence: "一句一译",
  daily: "每日积累", cet6_dictation: "精听", cet6_chunk: "意群",
  cet6: "六级", manual: "手动", ask: "问答", quiz: "测验", code: "代码调试",
};
const KIND_LABEL = { sentence: "句子", word: "单词短语" };
const KIND_HINT = {
  sentence: "正面是中文原句；先自己译一遍，再看参考译文和你上次的译文。",
  word: "正面是词或短语；先回忆词义，再显示释义。",
};
const PAGE_SIZE = 10;

let kind = "sentence";
let queue = [];
let index = 0;
let revealed = false;
let typed = "";
let counts = { sentence: {}, word: {} };
let newRemaining = 0;
let roundDone = 0;
let nodes = {};

function sourceLabel(card) {
  return SOURCE_LABELS[card?.source] || "英语";
}

function hashTab() {
  const query = (location.hash.split("?")[1] || "");
  return new URLSearchParams(query).get("tab") || "";
}

export async function mount(ctx) {
  const requested = hashTab();
  kind = requested === "word" ? "word" : "sentence";
  queue = [];
  index = 0;
  revealed = false;
  typed = "";
  roundDone = 0;
  nodes = {
    body: ctx.root.querySelector("#er-body"),
    progress: ctx.root.querySelector("#er-progress"),
    hint: ctx.root.querySelector("#er-hint"),
    tabs: Array.from(ctx.root.querySelectorAll(".er-tab")),
    sentenceCount: ctx.root.querySelector("#er-count-sentence"),
    wordCount: ctx.root.querySelector("#er-count-word"),
  };
  nodes.tabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.kind === kind);
    tab.addEventListener("click", () => switchKind(tab.dataset.kind));
  });
  nodes.body.addEventListener("click", onClick);
  nodes.body.addEventListener("input", (event) => {
    if (event.target.id === "er-typed") typed = event.target.value;
  });
  await refreshCounts();
  await startRound();
}

async function refreshCounts() {
  try {
    const [sentence, word] = await Promise.all([
      api.get("/api/review/stats?kind=sentence"),
      api.get("/api/review/stats?kind=word"),
    ]);
    counts = { sentence, word };
    paintCounts();
  } catch (error) {
    toast(error.message || "到期数没读出来", "err");
  }
}

function paintCounts() {
  nodes.sentenceCount.textContent = String(counts.sentence?.due ?? 0);
  nodes.wordCount.textContent = String(counts.word?.due ?? 0);
}

function paintHint() {
  nodes.hint.textContent = newRemaining > 0
    ? `今日新卡还剩 ${newRemaining} 张`
    : "今日新卡已用完";
}

async function switchKind(next) {
  if (!next || next === kind) return;
  kind = next;
  nodes.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.kind === kind));
  history.replaceState(null, "", `#/english-review?tab=${kind}`);
  await startRound();
}

async function startRound() {
  index = 0;
  revealed = false;
  typed = "";
  roundDone = 0;
  nodes.progress.textContent = `${KIND_LABEL[kind]} · 正在读取…`;
  nodes.hint.textContent = "";
  nodes.body.innerHTML = '<div class="empty">正在读到期卡片…</div>';
  try {
    const data = await api.get(
      `/api/review/queue?kind=${encodeURIComponent(kind)}&limit=${PAGE_SIZE}`);
    queue = Array.isArray(data.items) ? data.items : [];
    newRemaining = Number(data.new_remaining ?? 0);
    paintHint();
    renderCard();
  } catch (error) {
    nodes.progress.textContent = "读取失败";
    nodes.body.innerHTML = `<div class="empty"><strong>复习队列没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function renderCard() {
  if (!queue.length) {
    const label = KIND_LABEL[kind];
    nodes.progress.textContent = `${label} · 今天没有到期`;
    nodes.body.innerHTML = `<div class="empty"><strong>今天没有到期的${label}</strong>
      <p>${kind === "sentence"
        ? "写作或翻译批改后，错误句会自动进这里。"
        : "精听、翻译和每日积累收进来的词会按记忆曲线出现。"}</p></div>`;
    return;
  }
  if (index >= queue.length) {
    nodes.progress.textContent = `${KIND_LABEL[kind]} · 这一轮完成`;
    nodes.body.innerHTML = `<div class="empty"><strong>这一轮完成，共 ${roundDone} 张</strong>
      <p>做 10 张就够；还有到期卡的话，可以再来一轮。</p>
      <button class="btn btn-primary" type="button" id="er-more">再来一轮</button></div>`;
    refreshCounts();
    return;
  }
  const card = queue[index];
  nodes.progress.textContent =
    `${KIND_LABEL[kind]} · 第 ${index + 1} / ${queue.length} 张`;
  if (kind === "sentence") renderSentence(card);
  else renderWord(card);
}

function meta(card) {
  const tags = String(card.tags || "").split(/[,\s]+/).filter(Boolean).join(" · ");
  return `<div class="er-meta"><span class="er-source">${escapeHtml(sourceLabel(card))}</span>
    ${tags ? `<span>${escapeHtml(tags)}</span>` : ""}</div>`;
}

function ratings() {
  return `<div class="er-ratings">${[1, 2, 3, 4].map((rating) => `
    <button class="btn ${rating === 3 ? "btn-primary" : ""}" type="button"
      data-rating="${rating}">${RATING_LABELS[rating]}</button>`).join("")}</div>`;
}

function renderSentence(card) {
  nodes.body.innerHTML = `
    <div class="er-card">
      ${meta(card)}
      <div class="er-label">中文原句</div>
      <div class="er-prompt">${escapeHtml(card.question || "")}</div>
      ${revealed ? "" : `<textarea class="er-typed" id="er-typed"
        placeholder="先自己译一遍，再对照参考译文">${escapeHtml(typed)}</textarea>`}
      <div class="er-reveal"><button class="btn btn-primary" type="button" id="er-show">
        ${revealed ? "收起重译" : "看参考译文"}</button></div>
      <div class="er-answer" ${revealed ? "" : "hidden"}>
        <div class="er-block">
          <div class="er-label">参考译文</div>
          <div class="er-ref" id="er-ref"></div>
        </div>
        ${typed ? `<div class="er-block">
          <div class="er-label">我这次写的</div>
          <pre class="er-mine">${escapeHtml(typed)}</pre></div>` : ""}
        ${card.my_answer ? `<div class="er-block">
          <div class="er-label">我上次写的</div>
          <pre class="er-mine">${escapeHtml(card.my_answer)}</pre></div>` : ""}
        ${card.note ? `<div class="er-note">${escapeHtml(card.note)}</div>` : ""}
        ${ratings()}
      </div>
    </div>`;
  if (revealed) renderInto(nodes.body.querySelector("#er-ref"), card.answer || "（这条没有参考译文）");
}

function renderWord(card) {
  nodes.body.innerHTML = `
    <div class="er-card">
      ${meta(card)}
      <div class="er-word">${escapeHtml(card.word || "")}</div>
      ${card.context ? `<div class="er-context">${escapeHtml(card.context)}</div>` : ""}
      <div class="er-reveal"><button class="btn btn-primary" type="button" id="er-show">
        ${revealed ? "收起释义" : "显示释义"}</button></div>
      <div class="er-answer" ${revealed ? "" : "hidden"}>
        <div class="er-meaning">${escapeHtml(card.meaning || "（还没有释义）")}</div>
        ${ratings()}
      </div>
    </div>`;
}

async function onClick(event) {
  if (event.target.closest("#er-more")) {
    await startRound();
    return;
  }
  if (event.target.closest("#er-show")) {
    revealed = !revealed;
    renderCard();
    return;
  }
  const button = event.target.closest("button[data-rating]");
  if (!button || index >= queue.length) return;
  const card = queue[index];
  const rating = Number(button.dataset.rating || 3);
  const path = card.item_type === "vocab"
    ? `/api/review/vocab/${card.item_id}`
    : `/api/review/wrong/${card.item_id}`;
  button.disabled = true;
  try {
    const data = await api.post(path, { rating });
    toast(`${RATING_LABELS[rating]} · 下次 ${data.next_review}（${data.scheduled_days} 天后）`, "ok");
    roundDone += 1;
    index += 1;
    newRemaining = Math.max(0, newRemaining - 1);
    counts[kind] = { ...(counts[kind] || {}),
      due: Math.max(0, Number(counts[kind]?.due || 0) - 1) };
    paintHint();
    paintCounts();
    revealed = false;
    typed = "";
    renderCard();
  } catch (error) {
    button.disabled = false;
    toast(error.message || "复习没记上", "err");
  }
}
