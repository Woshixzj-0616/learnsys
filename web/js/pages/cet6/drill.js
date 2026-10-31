// 六级专项：从已标笔记的句子生成听写练习；漏听词自动进错题本/FSRS。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";

const SOURCE_LABELS = { note: "笔记句", coverage: "新题型" };

let panel = null;
let ctx = null;
let items = [];
let index = 0;
let plays = 0;
let answer = "";
let result = null;
let busy = false;
let audio = null;
let rate = 1;
let startedAt = 0;
let summary = null;

function current() {
  return items[index] || null;
}

function sentenceKey(item) {
  return `${item.paper_id}|${item.section}|${item.item}|${item.sentence}`;
}

function percent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function summaryHtml(data) {
  if (!data) return "";
  return `<div class="cet6-drill-summary">
    <span>近 ${data.range?.days || 30} 天</span>
    <strong>${data.sentences || 0}</strong><span>句</span>
    <strong>${percent(data.avg_score)}</strong><span>平均</span>
    <strong>${data.cards_added || 0}</strong><span>张卡</span>
  </div>`;
}

function topHtml(item) {
  const progress = Math.round(index * 100 / Math.max(items.length, 1));
  return `<div class="cet6-drill-top">
      <span class="cet6-kicker">专项听写 · 第 ${index + 1} / ${items.length} 句</span>
      <span class="cet6-chip">${escapeHtml(SOURCE_LABELS[item.source] || "练习")}</span>
    </div>
    <div class="cet6-drill-progress"><i style="width:${progress}%"></i></div>`;
}

function resultHtml(data) {
  const parts = (data.parts || []).map((part) => part.miss
    ? `<mark class="cet6-drill-miss">${escapeHtml(part.text)}</mark>`
    : escapeHtml(part.text)).join("");
  const missed = (data.missed || []).map((item) =>
    `<span class="cet6-chip">${escapeHtml(item.token)}</span>`).join("");
  const extra = (data.extra || []).map((token) =>
    `<span class="cet6-chip">${escapeHtml(token)}</span>`).join("");
  const cards = (data.cards || []).map((card) =>
    `<li>${escapeHtml(card.token)}</li>`).join("");
  return `<div class="cet6-drill-result">
    <div class="cet6-drill-score"><strong>${percent(data.score)}</strong>
      <span>内容词 ${data.content_matched} / ${data.content_total}</span></div>
    <p class="cet6-drill-label">原句（红色是漏听词）</p>
    <p class="cet6-drill-sentence">${parts}</p>
    ${missed ? `<p class="cet6-drill-label">漏听</p>
      <div class="cet6-drill-chips">${missed}</div>` : ""}
    ${extra ? `<p class="cet6-drill-label">多写</p>
      <div class="cet6-drill-chips">${extra}</div>` : ""}
    ${cards ? `<div class="cet6-drill-cards">
      <p class="cet6-drill-label">已加入复习（明天到期）</p>
      <ul>${cards}</ul></div>` : ""}
    <div class="cet6-actions">
      <button class="btn btn-primary" type="button" data-act="next">
        下一句 <kbd>Ctrl+Enter</kbd></button>
    </div>
  </div>`;
}

function cardHtml(item) {
  return `<div class="cet6-drill">
    ${topHtml(item)}
    <article class="cet6-drill-card">
      <div class="cet6-drill-audio">
        <button class="btn btn-primary" type="button" data-act="play">播放</button>
        <button class="btn btn-small" type="button" data-act="rate">
          ${rate === 1 ? "慢速 0.75x" : "常速 1x"}</button>
        <span class="cet6-drill-plays">已播 ${plays} 次</span>
        ${item.audio_url ? "" : '<span class="hint">这句没有音频文件</span>'}
      </div>
      <label class="cet6-drill-answer">
        <span>听一句，写下你听到的英文（Ctrl+Enter 提交）</span>
        <textarea id="cet6-drill-input" rows="3"
          placeholder="写下整句…">${escapeHtml(answer)}</textarea>
      </label>
      <div class="cet6-actions">
        <button class="btn btn-primary" type="button" data-act="submit">提交对照</button>
        <span class="hint">不会就留空提交；留空不建卡。</span>
      </div>
    </article>
    ${summaryHtml(summary)}
  </div>`;
}

function resultView(item, data) {
  return `<div class="cet6-drill">
    ${topHtml(item)}
    <article class="cet6-drill-card">${resultHtml(data)}</article>
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
  const box = panel.querySelector("#cet6-drill-input");
  if (box) {
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
  }
  ctx.setSub(`专项 · 第 ${index + 1}/${items.length} 句`);
}

function renderEmpty() {
  panel.innerHTML = `<div class="cet6-progress">
    <div class="cet6-progress-mark">✓</div>
    <h2>今天没有待练的句子</h2>
    <p>去精听工作台标几句笔记，或等明天的到期卡。</p>
    <div class="cet6-actions">
      <a class="btn btn-primary" href="#/cet6?tab=listening">去精听</a>
      <a class="btn" href="#/cet6?tab=review">去复习</a>
    </div>
  </div>`;
  ctx.setSub("专项 · 今天没有待练句");
}

function renderDone() {
  panel.innerHTML = `<div class="cet6-progress">
    <div class="cet6-progress-mark">✓</div>
    <h2>这一轮听写完了</h2>
    <p>完成 ${items.length} 句；漏听的内容词已进复习，明天到期。</p>
    ${summaryHtml(summary)}
    <div class="cet6-actions">
      <button class="btn btn-primary" type="button" data-act="again">再来 8 句</button>
      <a class="btn" href="#/cet6?tab=review">去复习</a>
    </div>
  </div>`;
  ctx.setSub(`专项 · 完成 ${items.length} 句`);
}

async function load() {
  panel.innerHTML = '<div class="empty">正在读取今天的专项…</div>';
  try {
    const [queueData, statsData] = await Promise.all([
      api.get("/api/cet6/drill/queue?limit=8"),
      api.get("/api/cet6/drill/stats?days=30"),
    ]);
    items = Array.isArray(queueData.items) ? queueData.items : [];
    summary = statsData || null;
    index = 0;
    plays = 0;
    answer = "";
    result = null;
    startedAt = Date.now();
    if (!items.length) {
      renderEmpty();
      return;
    }
    render();
  } catch (error) {
    panel.innerHTML = `<div class="empty"><strong>专项没读出来</strong>
      ${escapeHtml(error.message || "")}</div>`;
  }
}

function syncPlayButton() {
  const button = panel?.querySelector('[data-act="play"]');
  if (button) button.textContent = audio && !audio.paused ? "暂停" : "播放";
}

function syncPlayBadge() {
  const badge = panel?.querySelector(".cet6-drill-plays");
  if (badge) badge.textContent = `已播 ${plays} 次`;
}

function play() {
  const item = current();
  if (!item) return;
  if (!item.audio_url) {
    toast("这句没有音频文件", "err");
    return;
  }
  const key = sentenceKey(item);
  if (audio && audio.dataset.key !== key) {
    audio.pause();
    audio = null;
  }
  if (!audio) {
    audio = new Audio(item.audio_url);
    audio.dataset.key = key;
    audio.preload = "auto";
    audio.addEventListener("play", syncPlayButton);
    audio.addEventListener("pause", syncPlayButton);
    audio.addEventListener("ended", syncPlayButton);
  }
  if (audio.paused) {
    audio.playbackRate = rate;
    audio.play().then(() => {
      plays += 1;
      syncPlayBadge();
      syncPlayButton();
    }).catch(() => toast("音频播放失败", "err"));
  } else {
    audio.pause();
    syncPlayButton();
  }
}

function toggleRate(button) {
  rate = rate === 1 ? 0.75 : 1;
  if (audio) audio.playbackRate = rate;
  if (button) button.textContent = rate === 1 ? "慢速 0.75x" : "常速 1x";
}

async function submit() {
  const item = current();
  if (!item || busy || result) return;
  const box = panel?.querySelector("#cet6-drill-input");
  answer = box ? box.value : answer;
  busy = true;
  audio?.pause();
  try {
    const data = await api.post("/api/cet6/drill/attempt", {
      paper_id: item.paper_id,
      section: item.section,
      item: item.item,
      sentence: item.sentence,
      answer,
      duration_s: Math.round((Date.now() - startedAt) / 1000),
    });
    result = data;
    panel.innerHTML = resultView(item, data);
    ctx.setSub(`专项 · 第 ${index + 1}/${items.length} 句 · ${percent(data.score)}`);
    api.get("/api/cet6/drill/stats?days=30")
      .then((next) => { summary = next; })
      .catch(() => { /* 统计刷新失败不影响本轮 */ });
  } catch (error) {
    toast(error.message || "提交失败", "err");
  } finally {
    busy = false;
  }
}

function next() {
  if (!result) return;
  index += 1;
  plays = 0;
  answer = "";
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
  if (action === "play") play();
  else if (action === "rate") toggleRate(target);
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
  ctx.setActions('<a class="btn btn-small" href="#/cet6?tab=review">去复习</a>');
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
