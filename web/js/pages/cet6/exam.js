// 六级真题自评：整段真题音频 + 题干，逐题自评对/错，记 A/B/C 分段正确率。
// 试卷里没有选项和标准答案，所以这里只做「自评」，不冒充机器判分。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";

const SECTION_LABELS = { A: "长对话", B: "短文理解", C: "讲座/讲话" };

let panel = null;
let ctx = null;
let items = [];
let index = 0;
let marks = {};
let result = null;
let busy = false;
let audio = null;
let rate = 1;
let startedAt = 0;
let summary = null;

function current() {
  return items[index] || null;
}

function percent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function sectionLabel(item) {
  const letter = item.section_letter || "其他";
  return SECTION_LABELS[letter] ? `${letter} 段 · ${SECTION_LABELS[letter]}` : letter;
}

function summaryHtml(data) {
  if (!data) return "";
  return `<div class="cet6-drill-summary">
    <span>近 ${data.range?.days || 30} 天</span>
    <strong>${data.items || 0}</strong><span>段</span>
    <strong>${percent(data.self_accuracy)}</strong><span>自评正确率</span>
    <strong>${data.questions || 0}</strong><span>题</span>
  </div>`;
}

function markedCount() {
  return Object.keys(marks).length;
}

function allMarked(item) {
  return item && markedCount() >= item.questions.length;
}

function topHtml(item) {
  const progress = Math.round(index * 100 / Math.max(items.length, 1));
  return `<div class="cet6-drill-top">
      <span class="cet6-kicker">真题自评 · 第 ${index + 1} / ${items.length} 段</span>
      <span class="cet6-chip">${escapeHtml(sectionLabel(item))}</span>
    </div>
    <div class="cet6-drill-progress"><i style="width:${progress}%"></i></div>`;
}

function questionHtml(question) {
  const mark = marks[question.number];
  return `<li class="cet6-exam-q">
    <div class="cet6-exam-q-head">
      <span class="cet6-exam-no">第 ${question.number} 题</span>
      ${question.audio_url
        ? `<button class="cet6-exam-play" type="button" data-act="play"
            data-kind="question"
            data-url="${escapeHtml(question.audio_url)}">▶ 播放</button>`
        : '<span class="hint">没有单题音频</span>'}
      <span class="cet6-exam-marks">
        <button class="cet6-mark ${mark === "right" ? "on" : ""}" type="button"
          data-act="mark" data-number="${question.number}" data-value="right">✓ 对</button>
        <button class="cet6-mark ${mark === "wrong" ? "on" : ""}" type="button"
          data-act="mark" data-number="${question.number}" data-value="wrong">✗ 错</button>
      </span>
    </div>
    <p class="cet6-exam-stem">${escapeHtml(question.en)}</p>
  </li>`;
}

function cardHtml(item) {
  const remaining = item.questions.length - markedCount();
  const questions = item.questions.map(questionHtml).join("");
  return `<div class="cet6-drill cet6-exam">
    ${topHtml(item)}
    <article class="cet6-drill-card">
      <p class="cet6-exam-title">${escapeHtml(item.paper_title)} · ${escapeHtml(item.item)}</p>
      <div class="cet6-drill-audio">
        <button class="btn btn-primary" type="button" data-act="play"
          data-kind="content" data-url="${escapeHtml(item.audio_url)}">▶ 正文</button>
        <button class="btn btn-small" type="button" data-act="play"
          data-kind="questions" data-url="${escapeHtml(item.questions_url)}">▶ 题目</button>
        <button class="btn btn-small" type="button" data-act="rate">
          ${rate === 1 ? "慢速 0.75x" : "常速 1x"}</button>
        <span class="hint">听完后逐题自评；没有选项和标准答案，按你自己的作答判断。</span>
      </div>
      <ol class="cet6-exam-list">${questions}</ol>
      <div class="cet6-actions">
        <button class="btn btn-primary" type="button" data-act="submit"
          ${remaining > 0 ? "disabled" : ""}>提交自评</button>
        <button class="btn btn-small" type="button" data-act="all-right">全部标对</button>
        <span class="hint" id="cet6-exam-remaining">
          ${remaining > 0 ? `还有 ${remaining} 题未标` : "已标完，可以提交"}</span>
      </div>
    </article>
    ${summaryHtml(summary)}
  </div>`;
}

function resultHtml(item, data) {
  const wrong = (data.wrong || []).map((number) =>
    `<span class="cet6-chip">第 ${number} 题</span>`).join("");
  const transcript = (data.transcript || []).map((line) =>
    `<li>${escapeHtml(line)}</li>`).join("");
  return `<div class="cet6-drill cet6-exam">
    ${topHtml(item)}
    <article class="cet6-drill-card">
      <div class="cet6-drill-result">
        <div class="cet6-drill-score"><strong>${percent(data.self_accuracy)}</strong>
          <span>自评 ${data.correct_count} / ${data.question_count} 题</span></div>
        ${wrong ? `<p class="cet6-drill-label">错题</p>
          <div class="cet6-drill-chips">${wrong}</div>`
          : '<p class="cet6-exam-perfect">这一段全对。</p>'}
        ${transcript ? `<details class="cet6-exam-transcript">
          <summary>对照原文</summary><ol>${transcript}</ol></details>` : ""}
      </div>
      <div class="cet6-actions">
        <button class="btn btn-primary" type="button" data-act="next">
          下一段 <kbd>Ctrl+Enter</kbd></button>
      </div>
    </article>
    ${summaryHtml(summary)}
  </div>`;
}

function render() {
  const item = current();
  if (!item) {
    renderDone();
    return;
  }
  panel.innerHTML = cardHtml(item);
  syncAudioButtons();
  ctx.setSub(`专项 · 真题自评 · 第 ${index + 1}/${items.length} 段`);
}

function renderEmpty() {
  panel.innerHTML = `<div class="cet6-progress">
    <div class="cet6-progress-mark">✓</div>
    <h2>还没有可练的真题</h2>
    <p>先在精听工作台里打开一份试卷，让逐句进度同步到后台。</p>
    <div class="cet6-actions">
      <a class="btn btn-primary" href="#/cet6?tab=listening">去精听</a>
      <a class="btn" href="#/cet6?tab=drill">去逐句听写</a>
    </div>
  </div>`;
  ctx.setSub("专项 · 真题自评 · 没有可练的段");
}

function renderDone() {
  panel.innerHTML = `<div class="cet6-progress">
    <div class="cet6-progress-mark">✓</div>
    <h2>这一轮真题自评完了</h2>
    <p>完成 ${items.length} 段；可以点「再来一段」继续。</p>
    ${summaryHtml(summary)}
    <div class="cet6-actions">
      <button class="btn btn-primary" type="button" data-act="again">再来一段</button>
      <a class="btn" href="#/cet6?tab=stats">看统计</a>
    </div>
  </div>`;
  ctx.setSub(`专项 · 真题自评 · 完成 ${items.length} 段`);
}

async function load() {
  panel.innerHTML = '<div class="empty">正在读取真题…</div>';
  try {
    const [queueData, statsData] = await Promise.all([
      api.get("/api/cet6/exam/queue?limit=1"),
      api.get("/api/cet6/exam/stats?days=30"),
    ]);
    items = Array.isArray(queueData.items) ? queueData.items : [];
    summary = statsData || null;
    index = 0;
    marks = {};
    result = null;
    startedAt = Date.now();
    if (!items.length) {
      renderEmpty();
      return;
    }
    render();
  } catch (error) {
    panel.innerHTML = `<div class="empty"><strong>真题没读出来</strong>
      ${escapeHtml(error.message || "")}</div>`;
  }
}

function syncAudioButtons() {
  for (const button of panel?.querySelectorAll('[data-act="play"]') || []) {
    const active = audio && audio.dataset.url === button.dataset.url
      && !audio.paused;
    const kind = button.dataset.kind;
    if (kind === "content") button.textContent = active ? "⏸ 正文" : "▶ 正文";
    else if (kind === "questions") {
      button.textContent = active ? "⏸ 题目" : "▶ 题目";
    } else button.textContent = active ? "⏸ 暂停" : "▶ 播放";
  }
}

function playUrl(url) {
  if (!url) {
    toast("这句没有音频文件", "err");
    return;
  }
  if (audio && audio.dataset.url === url) {
    if (audio.paused) {
      audio.play().catch(() => toast("音频播放失败", "err"));
    } else {
      audio.pause();
    }
    syncAudioButtons();
    return;
  }
  if (audio) {
    audio.pause();
    audio = null;
  }
  audio = new Audio(url);
  audio.dataset.url = url;
  audio.preload = "auto";
  audio.playbackRate = rate;
  audio.addEventListener("play", syncAudioButtons);
  audio.addEventListener("pause", syncAudioButtons);
  audio.addEventListener("ended", syncAudioButtons);
  audio.play().catch(() => toast("音频播放失败", "err"));
  syncAudioButtons();
}

function toggleRate(button) {
  rate = rate === 1 ? 0.75 : 1;
  if (audio) audio.playbackRate = rate;
  if (button) button.textContent = rate === 1 ? "慢速 0.75x" : "常速 1x";
}

function mark(number, value) {
  if (result) return;
  if (marks[number] === value) delete marks[number];
  else marks[number] = value;
  render();
}

function markAllRight() {
  if (result) return;
  const item = current();
  if (!item) return;
  for (const question of item.questions) marks[question.number] = "right";
  render();
}

async function submit() {
  const item = current();
  if (!item || busy || result) return;
  if (!allMarked(item)) {
    toast("还有题没标", "err");
    return;
  }
  busy = true;
  audio?.pause();
  try {
    const wrong = item.questions
      .filter((question) => marks[question.number] === "wrong")
      .map((question) => question.number);
    const data = await api.post("/api/cet6/exam/attempt", {
      paper_id: item.paper_id,
      section: item.section,
      item: item.item,
      wrong,
      duration_s: Math.round((Date.now() - startedAt) / 1000),
    });
    try {
      summary = await api.get("/api/cet6/exam/stats?days=30");
    } catch {
      // 统计刷新失败不影响本轮结果
    }
    result = data;
    panel.innerHTML = resultHtml(item, data);
    ctx.setSub(`专项 · 真题自评 · ${percent(data.self_accuracy)}`);
  } catch (error) {
    toast(error.message || "提交失败", "err");
  } finally {
    busy = false;
  }
}

function next() {
  if (!result) return;
  index += 1;
  marks = {};
  result = null;
  startedAt = Date.now();
  if (audio) {
    audio.pause();
    audio = null;
  }
  if (index >= items.length) {
    renderDone();
  } else {
    render();
  }
}

function onClick(event) {
  const target = event.target.closest("[data-act]");
  if (!target || !panel?.contains(target)) return;
  event.preventDefault();
  const action = target.dataset.act;
  if (action === "play") playUrl(target.dataset.url);
  else if (action === "rate") toggleRate(target);
  else if (action === "mark") mark(Number(target.dataset.number), target.dataset.value);
  else if (action === "all-right") markAllRight();
  else if (action === "submit") submit();
  else if (action === "next") next();
  else if (action === "again") load();
}

function onKey(event) {
  if (!panel) return;
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    if (result) next();
    else submit();
  }
}

export async function mount(context) {
  panel = context.panel;
  ctx = context.ctx;
  ctx.setActions('<a class="btn btn-small" href="#/cet6?tab=stats">看统计</a>');
  panel.addEventListener("click", onClick);
  document.addEventListener("keydown", onKey);
  await load();
  return () => {
    panel?.removeEventListener("click", onClick);
    document.removeEventListener("keydown", onKey);
    if (audio) {
      audio.pause();
      audio = null;
    }
    panel = null;
    ctx = null;
    items = [];
    summary = null;
  };
}
