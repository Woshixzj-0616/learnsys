// 英语复习：句子 / 单词短语两个 tab，共用一套 FSRS 队列。
// 交互原则：先自己写/译，再看答案；切页后本轮进度接着走（sessionStorage）。
import { api } from "../api.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, toast } from "../ui.js";
import {
  ROUND_SIZE, cardKey, clearRound, loadRound, localDay, matchesAnswer,
  saveRound, shouldDecrementQuota, wordPrompt, writingStage,
} from "./english-review-round.js";
import { writingCardHtml } from "./english-review-writing.js";

const RATING_LABELS = { 1: "忘了", 2: "模糊", 3: "记得", 4: "简单" };
const SOURCE_LABELS = {
  writing: "写作", translation: "翻译", sentence: "一句一译",
  daily: "每日积累", cet6_dictation: "精听", cet6_chunk: "意群",
  cet6: "六级", manual: "手动", ask: "问答", quiz: "测验", code: "代码调试",
};
const KIND_LABEL = { sentence: "句子", word: "单词短语" };
const MATCH_TEXT = {
  same: "和参考一致",
  close: "基本一致",
  different: "和参考不同，对照看看是不是同义表达",
};

let kind = "sentence";
let ctxRef = null;
let queue = [];
let index = 0;
let revealed = false;
let typed = "";
let hintUsed = false;
let counts = { sentence: {}, word: {} };
let reviewed = { sentence: 0, word: 0 };
let countsLoaded = false;
let newRemaining = 0;
let quotaTypes = [];
let roundDone = 0;
let batchStart = 0;     // 本批第一张之前的已完成数；显示进度用 batchStart + index
let nodes = {};
let submitting = false;
let mountSeq = 0;
let detach = null;
let draftTimer = null;

function storage() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function loadState() {
  return loadRound(storage(), kind, localDay());
}

function saveState(patch) {
  return saveRound(storage(), kind, localDay(), patch);
}

function sourceLabel(card) {
  return SOURCE_LABELS[card?.source] || "英语";
}

function cardStage(card) {
  return card?.item_type === "accum" && card?.accum_kind === "writing"
    ? writingStage(card) : 0;
}

function hashTab() {
  const query = (location.hash.split("?")[1] || "");
  return new URLSearchParams(query).get("tab") || "";
}

export async function mount(ctx) {
  const seq = ++mountSeq;
  ctxRef = ctx;
  // 独立页读 #/english-review?tab=；嵌进英语聚合页时由外层把 kind 放进 ctx.query。
  const requested = ctx.query?.get?.("kind") || hashTab();
  kind = requested === "word" ? "word" : "sentence";
  queue = [];
  index = 0;
  revealed = false;
  typed = "";
  hintUsed = false;
  roundDone = 0;
  counts = { sentence: {}, word: {} };
  reviewed = { sentence: 0, word: 0 };
  countsLoaded = false;
  newRemaining = 0;
  quotaTypes = [];
  submitting = false;
  nodes = {
    body: ctx.root.querySelector("#er-body"),
    progress: ctx.root.querySelector("#er-progress"),
    hint: ctx.root.querySelector("#er-hint"),
    tabs: Array.from(ctx.root.querySelectorAll(".er-tab")),
    sentenceCount: ctx.root.querySelector("#er-count-sentence"),
    wordCount: ctx.root.querySelector("#er-count-word"),
  };
  markTabs();
  attach(ctx.root.querySelector(".english-review-page") || ctx.root);
  await refreshCounts();
  if (seq !== mountSeq) return;
  await startRound();
  return unmount;
}

export function unmount() {
  mountSeq += 1;
  persistDraft();
  clearTimeout(draftTimer);
  detach?.();
  detach = null;
  ctxRef = null;
  nodes = {};
  submitting = false;
}

function attach(root) {
  detach?.();
  root.addEventListener("click", onClick);
  root.addEventListener("input", onInput);
  detach = () => {
    root.removeEventListener("click", onClick);
    root.removeEventListener("input", onInput);
  };
}

function markTabs() {
  nodes.tabs?.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.kind === kind);
  });
}

async function refreshCounts() {
  const seq = mountSeq;
  try {
    const [sentence, word] = await Promise.all([
      api.get("/api/review/stats?kind=sentence"),
      api.get("/api/review/stats?kind=word"),
    ]);
    if (seq !== mountSeq) return;
    counts = { sentence, word };
    reviewed = {
      sentence: Number(sentence?.reviewed_today || 0),
      word: Number(word?.reviewed_today || 0),
    };
    countsLoaded = true;
    paintCounts();
  } catch (error) {
    if (seq !== mountSeq) return;
    countsLoaded = false;
    toast(error.message || "到期数没读出来", "err");
  }
}

function paintCounts() {
  nodes.sentenceCount.textContent = String(counts.sentence?.due ?? 0);
  nodes.wordCount.textContent = String(counts.word?.due ?? 0);
}

function paintHint() {
  const quotaName = kind === "sentence" ? "旧错题新卡" : "旧生词新卡";
  nodes.hint.textContent = newRemaining > 0
    ? `${quotaName}还剩 ${newRemaining} 张（每日积累另计）`
    : `${quotaName}已用完（每日积累另计）`;
}

async function switchKind(next) {
  if (!next || next === kind) return;
  persistDraft();
  submitting = false;
  kind = next;
  markTabs();
  if (typeof ctxRef?.onKind === "function") {
    ctxRef.onKind(kind);              // 聚合页自己写 #/english?tab=review&kind=
  } else {
    history.replaceState(null, "", `#/english-review?tab=${kind}`);
  }
  await startRound();
}

async function startRound({ reset = false } = {}) {
  const seq = mountSeq;
  index = 0;
  revealed = false;
  typed = "";
  hintUsed = false;
  if (reset) clearRound(storage(), kind, localDay());
  const saved = reset ? null : loadState();
  if (saved) {
    // session 是本轮位置的唯一来源；不再用今日复习数回夹，避免把进度往回拉。
    roundDone = Math.min(saved.done || 0, ROUND_SIZE);
    saveState({ done: roundDone, current: saved.current || null });
  } else if (countsLoaded && !reset) {
    // 没有 session（换标签页 / 重启 / 刚升级）时，不要把今天已复习过的卡再发一遍：
    // 以今天本 tab 的实际复习数作为本轮进度；「再来一轮」才从 0 开始。
    roundDone = Math.min(ROUND_SIZE, Number(reviewed[kind] || 0));
  } else {
    roundDone = 0;
  }
  batchStart = roundDone;

  nodes.progress.textContent = `${KIND_LABEL[kind]} · 正在读取…`;
  nodes.hint.textContent = "";
  nodes.body.innerHTML = '<div class="empty">正在读到期卡片…</div>';

  const remaining = ROUND_SIZE - roundDone;
  if (remaining <= 0) {
    queue = [];
    renderCard();
    return;
  }
  try {
    const data = await api.get(
      `/api/review/queue?kind=${encodeURIComponent(kind)}&limit=${remaining}`);
    if (seq !== mountSeq) return;
    queue = Array.isArray(data.items) ? data.items : [];
    quotaTypes = Array.isArray(data.quota_types) ? data.quota_types : [];
    newRemaining = Number(data.new_remaining ?? 0);
    const firstStage = queue.length ? cardStage(queue[0]) : 0;
    if (saved?.current && queue.length
        && cardKey(queue[0]) === saved.current.key
        && Number(saved.current.stage ?? firstStage) === firstStage) {
      typed = String(saved.current.typed || "");
      revealed = !!saved.current.revealed;
      hintUsed = !!saved.current.hintUsed;
    }
    paintHint();
    renderCard();
  } catch (error) {
    if (seq !== mountSeq) return;
    nodes.progress.textContent = "读取失败";
    nodes.body.innerHTML = `<div class="empty"><strong>复习队列没读出来</strong>
      ${escapeHtml(error.message || error)}</div>`;
  }
}

function renderCard() {
  const label = KIND_LABEL[kind];
  if (!queue.length) {
    if (roundDone > 0) renderRoundDone();
    else renderEmpty();
    return;
  }
  if (index >= queue.length) {
    renderRoundDone();
    return;
  }
  const card = queue[index];
  const shownTotal = Math.min(ROUND_SIZE, batchStart + queue.length);
  const number = Math.min(batchStart + index + 1, shownTotal);
  nodes.progress.textContent =
    `${label} · 第 ${number} / ${shownTotal} 张 · 今日已复习 ${reviewed[kind] || 0} 张`;
  if (kind === "sentence") renderSentence(card);
  else renderWord(card);
}

function renderEmpty() {
  const label = KIND_LABEL[kind];
  nodes.progress.textContent = `${label} · 今天没有到期`;
  nodes.body.innerHTML = `<div class="empty"><strong>今天没有到期的${label}</strong>
    <p>${kind === "sentence"
      ? "写作或翻译批改后，错误句会自动进这里。"
      : "精听、翻译和每日积累收进来的词会按记忆曲线出现。"}</p>
    ${reviewed[kind] ? `<p class="hint">今日已复习 ${reviewed[kind]} 张</p>` : ""}</div>`;
}

function renderRoundDone() {
  nodes.progress.textContent =
    `${KIND_LABEL[kind]} · 这一轮完成，共 ${roundDone} 张 · 今日已复习 ${reviewed[kind] || 0} 张`;
  nodes.body.innerHTML = `<div class="empty"><strong>这一轮完成，共 ${roundDone} 张</strong>
    <p>${roundDone >= ROUND_SIZE
      ? "做满 10 张；还想继续可以再来一轮。"
      : "今天到期的就这些；新卡明天再来。"}</p>
    <button class="btn btn-primary" type="button" id="er-more">再来一轮</button></div>`;
  refreshCounts();
}

function meta(card) {
  const tags = String(card.tags || "").split(/[,\s]+/).filter(Boolean).join(" · ");
  return `<div class="er-meta"><span class="er-source">${escapeHtml(sourceLabel(card))}</span>
    ${tags ? `<span>${escapeHtml(tags)}</span>` : ""}</div>`;
}

const RATING_HINTS = {
  1: ["几乎没写出来", "写出大意，句型没套上", "句型用上，个别词不同", "准确，还能换说法"],
  2: ["想不起来", "只想起一半", "基本还原", "完整准确"],
  3: ["写不出", "写了但句型没用对", "句型用对", "句型表达自然"],
};

function ratings(stage = 0) {
  const hints = RATING_HINTS[stage] || [];
  return `<div class="er-ratings${hints.length ? " anchors" : ""}">${[1, 2, 3, 4].map((rating) => `
    <button class="btn ${rating === 3 ? "btn-primary" : ""}" type="button"
      data-rating="${rating}"><span class="er-rating-main">${RATING_LABELS[rating]}</span>
      ${hints[rating - 1] ? `<small>${escapeHtml(hints[rating - 1])}</small>` : ""}</button>`).join("")}</div>`;
}

function typedBlock() {
  return `<div class="er-block">
    <div class="er-label">我这次写的</div>
    <pre class="er-mine">${escapeHtml(typed)}</pre></div>`;
}

function sentenceInput() {
  return `<textarea class="er-typed" id="er-typed" autocomplete="off"
    autocapitalize="off" spellcheck="false"
    placeholder="先自己译一遍，再对照参考译文">${escapeHtml(typed)}</textarea>`;
}

function renderSentence(card) {
  if (card.item_type === "accum" && card.accum_kind === "writing") {
    renderWritingPattern(card);
    return;
  }
  nodes.body.innerHTML = `
    <div class="er-card">
      ${meta(card)}
      <div class="er-label">中文原句</div>
      <div class="er-prompt">${escapeHtml(card.question || "")}</div>
      ${revealed ? "" : sentenceInput()}
      <div class="er-reveal"><button class="btn btn-primary" type="button" id="er-show">
        ${revealed ? "收起重译" : "看参考译文"}</button></div>
      <div class="er-answer" ${revealed ? "" : "hidden"}>
        <div class="er-block">
          <div class="er-label">参考译文</div>
          <div class="er-ref" id="er-ref"></div>
        </div>
        ${typed ? typedBlock() : ""}
        ${card.my_answer ? `<div class="er-block">
          <div class="er-label">我上次写的</div>
          <pre class="er-mine">${escapeHtml(card.my_answer)}</pre></div>` : ""}
        ${card.note ? `<div class="er-note">${escapeHtml(card.note)}</div>` : ""}
        ${ratings()}
      </div>
    </div>`;
  if (revealed) {
    renderInto(nodes.body.querySelector("#er-ref"),
      card.answer || "（这条没有参考译文）");
  }
}

function renderWritingPattern(card) {
  const stage = writingStage(card);
  nodes.body.innerHTML = writingCardHtml(card, {
    stage, typed, revealed, hintUsed,
  }, {
    metaHtml: meta(card),
    ratingsHtml: ratings(stage),
  });
}

function renderWord(card) {
  const info = wordPrompt(card);
  const isAccum = card.accum_kind === "translation";
  const promptLabel = isAccum ? "中文短语" : (info.direction === "zh2en" ? "中文词义" : "英文单词");
  const answerLabel = isAccum ? "英文表达" : (info.direction === "zh2en" ? "英文单词" : "释义");
  const placeholder = info.direction === "zh2en"
    ? "写出英文；想不起来就点下面看答案"
    : "写出中文意思；想不起来就点下面看答案";
  const compare = revealed && typed ? matchesAnswer(info.answer, typed) : "";
  nodes.body.innerHTML = `
    <div class="er-card">
      ${meta(card)}
      <div class="er-label">${promptLabel}</div>
      <div class="er-word">${escapeHtml(info.prompt || "")}</div>
      ${revealed ? "" : `<textarea class="er-typed er-typed-word" id="er-typed"
        autocomplete="off" autocapitalize="off" spellcheck="false"
        placeholder="${escapeHtml(placeholder)}">${escapeHtml(typed)}</textarea>`}
      <div class="er-reveal"><button class="btn btn-primary" type="button" id="er-show">
        ${revealed ? "收起答案" : "看答案"}</button></div>
      <div class="er-answer" ${revealed ? "" : "hidden"}>
        <div class="er-label">${answerLabel}</div>
        <div class="er-meaning">${escapeHtml(info.answer || "（还没有答案）")}</div>
        ${typed ? typedBlock() : ""}
        ${compare ? `<div class="er-match ${compare === "different" ? "off" : "ok"}">
          ${escapeHtml(MATCH_TEXT[compare])}</div>` : ""}
        ${info.hint ? `<div class="er-note">${escapeHtml(info.hint)}</div>` : ""}
        ${ratings()}
      </div>
    </div>`;
}

function onInput(event) {
  if (event.target.id !== "er-typed") return;
  typed = event.target.value;
  if (event.isComposing) return;      // 中文输入法拼音中间态不写草稿
  clearTimeout(draftTimer);
  draftTimer = setTimeout(persistDraft, 160);
}

// 保存本轮位置 + 当前卡草稿；切页/刷新后靠它续上进度。
function persistDraft() {
  const card = queue[index];
  saveState({
    done: roundDone,
    current: card ? {
      key: cardKey(card), stage: cardStage(card), typed, revealed, hintUsed,
    } : null,
  });
}

async function onClick(event) {
  const tab = event.target.closest(".er-tab");
  if (tab) {
    switchKind(tab.dataset.kind)
      .catch((error) => toast(error.message || "切换失败", "err"));
    return;
  }
  if (event.target.closest("#er-more")) {
    await startRound({ reset: true });
    return;
  }
  if (event.target.closest("#er-hint")) {
    hintUsed = true;
    clearTimeout(draftTimer);
    persistDraft();
    renderCard();
    nodes.body.querySelector("#er-typed")?.focus();
    return;
  }
  if (event.target.closest("#er-show")) {
    revealed = !revealed;
    clearTimeout(draftTimer);
    persistDraft();
    renderCard();
    return;
  }
  const button = event.target.closest("button[data-rating]");
  if (!button || index >= queue.length || submitting) return;
  await rateCard(button, Number(button.dataset.rating || 3));
}

async function rateCard(button, rating) {
  const card = queue[index];
  if (!card) return;
  const seq = mountSeq;
  const ratedKind = kind;
  const ratedDay = localDay();
  const nextDone = Math.min(ROUND_SIZE, roundDone + 1);
  submitting = true;
  nodes.body.querySelectorAll("button[data-rating]")
    .forEach((node) => { node.disabled = true; });
  try {
    const path = card.item_type === "vocab"
      ? `/api/review/vocab/${card.item_id}`
      : card.item_type === "accum"
        ? `/api/review/accum/${card.item_id}`
        : `/api/review/wrong/${card.item_id}`;
    const data = await api.post(path, { rating });

    // 先把事实写回 session，再判断当前页是否还停在原 tab。
    // reviewed_today 是「今天动过的不同卡片」；今天已动过的卡再次评分不重复计数。
    if (String(card.last_review || "").slice(0, 10) !== ratedDay) {
      reviewed[ratedKind] = Number(reviewed[ratedKind] || 0) + 1;
    }
    saveRound(storage(), ratedKind, ratedDay,
      { done: nextDone, current: null });
    if (seq !== mountSeq || kind !== ratedKind) return;

    roundDone = nextDone;
    counts[ratedKind] = { ...(counts[ratedKind] || {}),
      due: Math.max(0, Number(counts[ratedKind]?.due || 0) - 1) };
    if (shouldDecrementQuota(card, quotaTypes)) {
      newRemaining = Math.max(0, newRemaining - 1);
    }
    paintHint();
    paintCounts();
    toast(`${RATING_LABELS[rating]} · 下次 ${data.next_review}（${data.scheduled_days} 天后）`, "ok");
    index += 1;
    revealed = false;
    typed = "";
    hintUsed = false;
    renderCard();
  } catch (error) {
    if (seq === mountSeq && kind === ratedKind) button.disabled = false;
    toast(error.message || "复习没记上", "err");
  } finally {
    submitting = false;
  }
}
