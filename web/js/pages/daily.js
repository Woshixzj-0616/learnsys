// 每日积累：写作好句 + 翻译重点词 + 从精听笔记解析出的纠音点。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

let root = null;
let ctx = null;
let state = { day: "", data: null, audio: null, playing: "", history: false };

function todayText() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function percent(done, total) {
  return total ? Math.round((Number(done) || 0) * 100 / total) : 0;
}

function findPron(id) {
  return (state.data?.items?.pron || [])
    .find((item) => Number(item.id) === Number(id)) || null;
}

function writingHtml(item) {
  const payload = item.payload || {};
  const done = item.status !== "new";
  return `<article class="daily-card daily-writing ${done ? "done" : ""}">
    <div class="daily-card-head">
      <p class="eyebrow">${escapeHtml(payload.context || "写作好句")}</p>
      <span class="daily-status">${done ? "已积累" : "未读"}</span>
    </div>
    <p class="daily-good">${escapeHtml(payload.en || "")}</p>
    <details class="daily-weak">
      <summary>看弱版</summary>
      <p>${escapeHtml(payload.weak || "")}</p>
    </details>
    <p class="daily-why">${escapeHtml(payload.why || "")}</p>
    <button class="btn btn-small" type="button" data-act="read" data-id="${item.id}"
      ${done ? "disabled" : ""}>${done ? "✓ 已积累" : "已积累"}</button>
  </article>`;
}

function termHtml(item) {
  const payload = item.payload || {};
  const done = item.status !== "new";
  const note = payload.note
    ? `<small>${escapeHtml(payload.note)}</small>` : "";
  return `<li class="daily-term ${done ? "done" : ""}">
    <div class="daily-term-main">
      <b class="daily-zh">${escapeHtml(payload.zh || "")}</b>
      <span class="daily-arrow">→</span>
      <span class="daily-en">${escapeHtml(payload.en || "")}</span>
      ${note}
    </div>
    <div class="daily-term-actions">
      <button class="btn btn-small" type="button" data-act="vocab"
        data-id="${item.id}">加入生词本</button>
      <button class="btn btn-small" type="button" data-act="read"
        data-id="${item.id}" ${done ? "disabled" : ""}>${done ? "✓ 已读" : "已读"}</button>
    </div>
  </li>`;
}

function pronHtml(item) {
  const payload = item.payload || {};
  const heard = payload.heard_as
    ? `<span class="daily-heard">你听成 ${escapeHtml(payload.heard_as)}</span>` : "";
  const note = payload.note
    ? `<p class="daily-note">${escapeHtml(payload.note)}</p>` : "";
  const audio = payload.audio || {};
  const wordButton = audio.url
    ? `<button class="btn btn-small" type="button" data-act="play-word"
        data-id="${item.id}">▶ 这个词</button>` : "";
  const sentenceButton = payload.sentence_audio
    ? `<button class="btn btn-small" type="button" data-act="play-sentence"
        data-id="${item.id}">▶ 整句</button>` : "";
  const mastered = item.status === "mastered";
  return `<li class="daily-pron ${item.status}">
    <div class="daily-pron-head">
      <b class="daily-target">${escapeHtml(payload.target || "")}</b>
      ${heard}
      <span class="daily-kind">${escapeHtml(payload.kind_label || "没听出")}</span>
    </div>
    ${note}
    <p class="daily-context">${escapeHtml(payload.sentence || "")}</p>
    <div class="daily-pron-actions">
      ${wordButton}${sentenceButton}
      <button class="btn btn-small" type="button" data-act="master"
        data-id="${item.id}" ${mastered ? "disabled" : ""}>
        ${mastered ? "✓ 已掌握" : "已掌握"}</button>
    </div>
  </li>`;
}

function emptyPronHtml() {
  return `<li class="daily-empty">
    <p>今天没有新的纠音点。</p>
    <p class="hint">去精听，把没听出或听错的地方写进句子笔记；下一次会出现在这里。</p>
    <a class="btn btn-small" href="#/cet6?tab=listening">去精听</a>
  </li>`;
}

function render() {
  const data = state.data;
  if (!data) return;
  root.querySelector("#daily-date").textContent = data.is_today
    ? `今天 · ${data.day}` : data.day;
  root.querySelector("#daily-streak").textContent = `连续 ${data.streak || 0} 天`;
  root.querySelector("#daily-progress").textContent =
    `已过 ${data.done || 0} / ${data.total || 0} 条`;
  root.querySelector("#daily-bar-fill").style.width =
    `${percent(data.done, data.total)}%`;
  root.querySelector("#daily-today").hidden = Boolean(data.is_today);
  const readAll = root.querySelector("#daily-readall");
  if (readAll) readAll.hidden = Number(data.total || 0) > 0
    && Number(data.done || 0) >= Number(data.total || 0);

  const writing = data.items?.writing || [];
  const terms = data.items?.translation || [];
  const pron = data.items?.pron || [];
  root.querySelector("#daily-writing-count").textContent = `${writing.length} 句`;
  root.querySelector("#daily-translation-count").textContent = `${terms.length} 个`;
  root.querySelector("#daily-pron-count").textContent = `${pron.length} 条`;
  root.querySelector("#daily-writing").innerHTML =
    writing.map(writingHtml).join("") || '<p class="hint">今天没有好句。</p>';
  root.querySelector("#daily-translation").innerHTML =
    terms.map(termHtml).join("") || '<li class="hint">今天没有翻译词。</li>';
  root.querySelector("#daily-pron").innerHTML =
    pron.map(pronHtml).join("") || emptyPronHtml();
}

function stopAudio() {
  if (state.audio) {
    state.audio.pause();
    state.audio = null;
  }
  state.playing = "";
}

function syncAudio() {
  const playing = Boolean(state.audio && !state.audio.paused);
  for (const button of root?.querySelectorAll(
    '[data-act="play-word"],[data-act="play-sentence"]') || []) {
    const kind = button.dataset.act === "play-word" ? "word" : "sentence";
    const key = `${kind}-${button.dataset.id}`;
    const on = playing && state.playing === key;
    button.textContent = on ? "⏸ 播放中"
      : (kind === "word" ? "▶ 这个词" : "▶ 整句");
  }
}

function playSegment(url, start, end, key) {
  if (!url) {
    toast("这条没有音频", "err");
    return;
  }
  if (state.audio && state.audio.dataset.url !== url) stopAudio();
  if (!state.audio) {
    state.audio = new Audio(url);
    state.audio.dataset.url = url;
    state.audio.preload = "auto";
    state.audio.addEventListener("play", syncAudio);
    state.audio.addEventListener("pause", syncAudio);
    state.audio.addEventListener("ended", () => {
      state.playing = "";
      syncAudio();
    });
    state.audio.addEventListener("timeupdate", () => {
      const stop = Number(state.audio?.dataset.end || 0);
      if (stop && state.audio.currentTime >= stop) {
        state.audio.pause();
        state.audio.dataset.end = "";
        state.playing = "";
        syncAudio();
      }
    });
  }
  if (state.playing === key && !state.audio.paused) {
    state.audio.pause();
    state.playing = "";
    syncAudio();
    return;
  }
  const begin = () => {
    state.audio.currentTime = Number(start) || 0;
    state.audio.dataset.end = end ? String(end) : "";
    state.audio.play().catch(() => toast("音频播放失败", "err"));
    state.playing = key;
    syncAudio();
  };
  if (state.audio.readyState >= 1) begin();
  else state.audio.addEventListener("loadedmetadata", begin, { once: true });
}

async function reload() {
  await load(state.day);
}

async function load(day) {
  stopAudio();
  try {
    const data = await api.get(`/api/daily?day=${encodeURIComponent(day)}`);
    state.day = data.day || day;
    state.data = data;
    render();
  } catch (error) {
    root.querySelector("#daily-date").textContent = "读取失败";
    toast(error.message || "每日积累没加载出来", "err");
  }
}

async function loadHistory(force = false) {
  if (state.history && !force) return;
  try {
    const data = await api.get("/api/daily/history?limit=30");
    const days = data.days || [];
    const box = root.querySelector("#daily-history");
    box.innerHTML = days.length ? days.map((row) =>
      `<button class="daily-history-day ${row.day === state.day ? "active" : ""}"
        type="button" data-act="day" data-day="${row.day}">
        <span>${row.day}</span>
        <em>${row.done}/${row.total}${row.total && row.done >= row.total ? " ✓" : ""}</em>
      </button>`).join("") : '<p class="hint">还没有往期记录。</p>';
    state.history = true;
  } catch (error) {
    toast(error.message || "往期没读出来", "err");
  }
}

async function onClick(event) {
  const target = event.target.closest("[data-act]");
  if (!target || !root?.contains(target)) return;
  const action = target.dataset.act;
  const id = target.dataset.id;
  try {
    if (action === "read" || action === "master") {
      await api.post(`/api/daily/item/${id}/status`,
        { status: action === "master" ? "mastered" : "read" });
      await reload();
    } else if (action === "vocab") {
      const result = await api.post(`/api/daily/term/${id}/vocab`, {});
      toast(result.created ? "已加入生词本" : "这个生词已经在生词本里");
      await reload();
    } else if (action === "play-word") {
      const item = findPron(id);
      const audio = item?.payload?.audio || {};
      playSegment(audio.url, audio.start, audio.end, `word-${id}`);
    } else if (action === "play-sentence") {
      const item = findPron(id);
      playSegment(item?.payload?.sentence_audio, 0, null, `sentence-${id}`);
    } else if (action === "day") {
      await load(target.dataset.day);
      await loadHistory(true);
    } else if (action === "today") {
      await load(todayText());
    }
  } catch (error) {
    toast(error.message || "操作失败", "err");
  }
}

export async function mount(context) {
  root = context.root;
  ctx = context;
  state = { day: todayText(), data: null, audio: null, playing: "", history: false };
  ctx.setSub("写作好句 + 翻译热词 + 你自己的纠音点，每天一小份");
  root.addEventListener("click", onClick);
  root.querySelector("#daily-today")?.addEventListener("click", () => {
    load(todayText());
  });
  root.querySelector("#daily-readall")?.addEventListener("click", async () => {
    try {
      await api.post(`/api/daily/read-all?day=${encodeURIComponent(state.day)}`, {});
      toast("今天的积累过完了");
      await reload();
    } catch (error) {
      toast(error.message || "操作失败", "err");
    }
  });
  root.querySelector("#daily-archive")?.addEventListener("toggle", (event) => {
    if (event.target.open) loadHistory();
  });
  await load(state.day);
  return () => {
    root?.removeEventListener("click", onClick);
    stopAudio();
    root = null;
    ctx = null;
    state = { day: "", data: null, audio: null, playing: "", history: false };
  };
}
