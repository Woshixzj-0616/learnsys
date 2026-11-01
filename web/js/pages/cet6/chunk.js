// 六级意群长句：整句听写，提交后按意群回放；漏听词自动进复习。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";

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
let playingChunk = -1;
let startedAt = 0;
let summary = null;

function current() {
  return items[index] || null;
}

// 给六级 AI 抽屉：当前长句、你的听写、意群切分。
export function context() {
  const item = current();
  if (!item) return null;
  const missed = (result?.missed || []).map((row) => row.token).join("、");
  return {
    object_type: "cet6_chunk",
    object_id: keyOf(item),
    title: `六级意群长句 · ${item.paper_title || item.paper_id} / ${item.section} / `
      + `${item.item} · 第 ${index + 1} 句（${item.word_count || 0} 词）`,
    surrounding: {
      原句: result?.expected || item.en || "",
      你的听写: result?.answer || answer || "（还没写）",
      意群切分: (result?.chunks || []).map((row) => row.text).join(" / "),
    },
    learning_state: {
      模式: "意群长句",
      进度: `${index + 1}/${items.length}`,
      得分: result ? percent(result.score) : "未提交",
      漏听词: missed || "无",
      多写: (result?.extra || []).join("、") || "无",
    },
  };
}

function keyOf(item) {
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
      <span class="cet6-kicker">意群长句 · 第 ${index + 1} / ${items.length} 句</span>
      <span class="cet6-chip">长句 ${item.word_count || 0} 词</span>
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
  const chunks = (data.chunks || []).map((chunk, index) =>
    `<li class="cet6-chunk-row">
      <button class="cet6-chunk-play" type="button" data-act="play-chunk"
        data-index="${index}">▶</button>
      <span class="cet6-chunk-no">意群 ${index + 1}</span>
      <span class="cet6-chunk-text">${escapeHtml(chunk.text)}</span>
    </li>`).join("");
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
    <div class="cet6-chunks">
      <p class="cet6-drill-label">这句话有 ${data.chunk_count} 个意群
        <span class="hint">点 ▶ 只听这一段</span></p>
      <ul class="cet6-chunk-list">${chunks}</ul>
    </div>
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
        <button class="btn btn-primary" type="button" data-act="play-whole">播放整句</button>
        <button class="btn btn-small" type="button" data-act="rate">
          ${rate === 1 ? "慢速 0.75x" : "常速 1x"}</button>
        <span class="cet6-drill-plays">已播 ${plays} 次</span>
        ${item.audio_url ? "" : '<span class="hint">这句没有音频文件</span>'}
      </div>
      <label class="cet6-drill-answer">
        <span>先听整句，写下你听到的英文（Ctrl+Enter 提交）</span>
        <textarea id="cet6-chunk-input" rows="3"
          placeholder="写下整句…">${escapeHtml(answer)}</textarea>
      </label>
      <div class="cet6-actions">
        <button class="btn btn-primary" type="button" data-act="submit">提交对照</button>
        <span class="hint">提交后按意群逐段回放；留空不建卡。</span>
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
  const box = panel.querySelector("#cet6-chunk-input");
  if (box) {
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
  }
  syncAudioButtons();
  ctx.setSub(`专项 · 意群长句 · 第 ${index + 1}/${items.length} 句`);
}

function renderEmpty() {
  panel.innerHTML = `<div class="cet6-progress">
    <div class="cet6-progress-mark">✓</div>
    <h2>今天没有待练的长句</h2>
    <p>去精听工作台标几句笔记，或等明天的到期卡；长句需要试卷带词级时间轴。</p>
    <div class="cet6-actions">
      <a class="btn btn-primary" href="#/cet6?tab=listening">去精听</a>
      <a class="btn" href="#/cet6?tab=review">去复习</a>
    </div>
  </div>`;
  ctx.setSub("专项 · 意群长句 · 今天没有待练句");
}

function renderDone() {
  panel.innerHTML = `<div class="cet6-progress">
    <div class="cet6-progress-mark">✓</div>
    <h2>这一轮长句练完了</h2>
    <p>完成 ${items.length} 句；漏听的内容词已进复习，明天到期。</p>
    ${summaryHtml(summary)}
    <div class="cet6-actions">
      <button class="btn btn-primary" type="button" data-act="again">再来 8 句</button>
      <a class="btn" href="#/cet6?tab=review">去复习</a>
    </div>
  </div>`;
  ctx.setSub(`专项 · 意群长句 · 完成 ${items.length} 句`);
}

async function load() {
  panel.innerHTML = '<div class="empty">正在读取长句…</div>';
  try {
    const [queueData, statsData] = await Promise.all([
      api.get("/api/cet6/chunk/queue?limit=8"),
      api.get("/api/cet6/chunk/stats?days=30"),
    ]);
    items = Array.isArray(queueData.items) ? queueData.items : [];
    summary = statsData || null;
    index = 0;
    plays = 0;
    answer = "";
    result = null;
    playingChunk = -1;
    startedAt = Date.now();
    if (!items.length) {
      renderEmpty();
      return;
    }
    render();
  } catch (error) {
    panel.innerHTML = `<div class="empty"><strong>长句没读出来</strong>
      ${escapeHtml(error.message || "")}</div>`;
  }
}

function ensureAudio(item) {
  const key = keyOf(item);
  if (audio && audio.dataset.key !== key) {
    audio.pause();
    audio = null;
  }
  if (!audio) {
    audio = new Audio(item.audio_url);
    audio.dataset.key = key;
    audio.preload = "auto";
    audio.addEventListener("play", syncAudioButtons);
    audio.addEventListener("pause", syncAudioButtons);
    audio.addEventListener("ended", () => {
      playingChunk = -1;
      syncAudioButtons();
    });
    audio.addEventListener("timeupdate", () => {
      const end = Number(audio.dataset.end || 0);
      if (end && audio.currentTime >= end) {
        audio.pause();
        audio.dataset.end = "";
        playingChunk = -1;
        syncAudioButtons();
      }
    });
  }
  return audio;
}

function syncAudioButtons() {
  const playing = Boolean(audio && !audio.paused);
  const whole = panel?.querySelector('[data-act="play-whole"]');
  if (whole) {
    whole.textContent = playing && playingChunk < 0 ? "暂停整句" : "播放整句";
  }
  for (const button of panel?.querySelectorAll('[data-act="play-chunk"]') || []) {
    const on = playing && Number(button.dataset.index) === playingChunk;
    button.textContent = on ? "⏸" : "▶";
  }
}

function playWhole() {
  const item = current();
  if (!item) return;
  if (!item.audio_url) {
    toast("这句没有音频文件", "err");
    return;
  }
  const player = ensureAudio(item);
  if (!player.paused && playingChunk < 0) {
    player.pause();
    return;
  }
  player.dataset.end = "";
  playingChunk = -1;
  if (player.currentTime > 0) player.currentTime = 0;
  player.playbackRate = rate;
  player.play().then(() => {
    plays += 1;
    const badge = panel?.querySelector(".cet6-drill-plays");
    if (badge) badge.textContent = `已播 ${plays} 次`;
    syncAudioButtons();
  }).catch(() => toast("音频播放失败", "err"));
}

function playChunk(number) {
  const item = current();
  const chunk = result?.chunks?.[number];
  if (!item || !chunk || !item.audio_url) {
    toast("这句没有音频文件", "err");
    return;
  }
  const player = ensureAudio(item);
  if (!player.paused && playingChunk === number) {
    player.pause();
    return;
  }
  const start = Number(chunk.start) || 0;
  const end = Number(chunk.end) || 0;
  const begin = () => {
    player.currentTime = start;
    player.dataset.end = String(end);
    player.playbackRate = rate;
    player.play().catch(() => toast("音频播放失败", "err"));
    playingChunk = number;
    syncAudioButtons();
  };
  if (player.readyState >= 1) begin();
  else player.addEventListener("loadedmetadata", begin, { once: true });
}

function toggleRate(button) {
  rate = rate === 1 ? 0.75 : 1;
  if (audio) audio.playbackRate = rate;
  if (button) button.textContent = rate === 1 ? "慢速 0.75x" : "常速 1x";
}

async function submit() {
  const item = current();
  if (!item || busy || result) return;
  const box = panel?.querySelector("#cet6-chunk-input");
  answer = box ? box.value : answer;
  busy = true;
  audio?.pause();
  playingChunk = -1;
  try {
    const data = await api.post("/api/cet6/chunk/attempt", {
      paper_id: item.paper_id,
      section: item.section,
      item: item.item,
      sentence: item.sentence,
      answer,
      duration_s: Math.round((Date.now() - startedAt) / 1000),
    });
    try {
      summary = await api.get("/api/cet6/chunk/stats?days=30");
    } catch {
      // 统计刷新失败不影响本轮结果
    }
    result = data;
    panel.innerHTML = resultView(item, data);
    ctx.setSub(`专项 · 意群长句 · 第 ${index + 1}/${items.length} 句 · ${percent(data.score)}`);
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
  playingChunk = -1;
  startedAt = Date.now();
  if (audio) {
    audio.pause();
    audio.dataset.end = "";
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
  if (action === "play-whole") playWhole();
  else if (action === "play-chunk") playChunk(Number(target.dataset.index));
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
