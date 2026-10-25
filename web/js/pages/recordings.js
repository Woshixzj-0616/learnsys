// 录像页：列表、播放、转写时间轴、幻灯片、AI 分析、打开文件夹、存资料、删除。
import { api } from "../api.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, toast } from "../ui.js";
import { createRecordControl } from "./recordings/record-control.js";
import { createAIPanel } from "./recordings/ai-panel.js";
import { bytesText, dateText, secondsText } from "./recordings/format.js";

let nodes = {};
let items = [];
let current = null;
let searchTimer = null;
let video = null;
let analysisTimer = null;
let analysisSeq = 0;
let recordControl = null;
let aiPanel = null;
let transcriptTimer = null;
let transcriptSeq = 0;
let aiController = null;
let aiSeq = 0;

function renderStats(totals) {
  const chips = nodes.stats.querySelectorAll("strong");
  if (chips.length < 3) return;
  chips[0].textContent = String(totals?.count ?? items.length);
  chips[1].textContent = secondsText(totals?.seconds ?? 0);
  chips[2].textContent = bytesText(totals?.bytes ?? 0);
}

function card(item) {
  const thumb = item.thumb_url
    ? `<img src="${escapeHtml(item.thumb_url)}" alt="" loading="lazy">`
    : '<span class="rec-thumb-empty">◉</span>';
  const missing = item.video_exists ? "" : '<span class="rec-badge danger">文件缺失</span>';
  return `<article class="rec-card" data-id="${item.id}">
    <button class="rec-thumb" type="button" data-open="${item.id}" aria-label="打开录像">${thumb}</button>
    <div class="rec-main">
      <div class="rec-card-top">
        <strong>${escapeHtml(item.title)}</strong>
        <span class="rec-badge">${secondsText(item.duration)}</span>${missing}
      </div>
      <div class="rec-meta">${escapeHtml(dateText(item.started_at))} · ${bytesText(item.video_bytes)}
        · 转写 ${item.transcripts} 段 / ${item.chars} 字</div>
      <div class="rec-preview">${escapeHtml(item.preview || "（还没有转写）")}</div>
    </div>
    <button class="btn" type="button" data-open="${item.id}">打开</button>
  </article>`;
}

function renderList() {
  if (!items.length) {
    nodes.list.innerHTML = `<div class="empty"><strong>还没有录像</strong>
      按 <kbd>Alt+Q</kbd> 打开快捷栏，点「录像」；停止后这里就会出现。</div>`;
    return;
  }
  nodes.list.innerHTML = items.map(card).join("");
  nodes.count.textContent = `${items.length} 段`;
}

function transcriptRows(rows, transcribing = false) {
  if (!rows.length) {
    return transcribing
      ? `<div class="empty">正在转写…视频已经保存，可以先用；页面会自动刷新一会儿。</div>`
      : `<div class="empty">这段还没有转写 —— 可能没听到声音，或者模型还在识别。</div>`;
  }
  return rows.map((row) => `<div class="rec-line">
    <button class="rec-time" type="button" data-at="${row.at}">${escapeHtml(row.clock)}</button>
    <span>${escapeHtml(row.text)}</span>
  </div>`).join("");
}

function slideGrid(slides) {
  if (!slides.length) return "";
  return `<details class="rec-slides" open>
    <summary>幻灯片 ${slides.length} 张</summary>
    <div class="rec-slide-grid">${slides.map((slide) =>
      `<a href="${escapeHtml(slide.url)}" target="_blank" rel="noreferrer">
        <img src="${escapeHtml(slide.url)}" alt="${escapeHtml(slide.name)}" loading="lazy">
      </a>`).join("")}</div>
  </details>`;
}

function stopPolling() {
  if (analysisTimer) {
    clearTimeout(analysisTimer);
    analysisTimer = null;
  }
  analysisSeq += 1;
}

function renderAnalysis(item) {
  const panel = nodes.detailBody.querySelector("#rec-analysis");
  const button = nodes.detailBody.querySelector("#rec-analyze");
  if (!panel) return;
  const analysis = item.analysis || null;
  const busy = Boolean(analysis && ["pending", "running"].includes(analysis.status));
  if (button) {
    button.disabled = busy;
    button.textContent = busy ? "分析中…" : (analysis?.status === "done" ? "重新分析" : "分析这段");
  }
  if (!analysis) {
    panel.innerHTML = `<div class="rec-analysis-empty">
      <strong>还没分析这段</strong>
      <p>把转写和幻灯片 OCR 交给 AI，生成时间线提纲、关键要点、术语表、值得追问的地方。</p>
    </div>`;
    return;
  }
  if (busy) {
    panel.innerHTML = `<div class="rec-analysis-progress">
      <strong>正在分析…</strong>
      <span>转写和幻灯片越多越久；可以先看视频。</span>
    </div>`;
    startPolling(item.id);
    return;
  }
  if (analysis.status === "done") {
    const content = analysis.content || {};
    panel.innerHTML = `<div class="rec-analysis-head">
      <strong>分析</strong>
      <span class="rec-analysis-meta">${escapeHtml(analysis.model || "")}${
        analysis.ms ? ` · ${(analysis.ms / 1000).toFixed(1)} 秒` : ""}</span>
    </div><div class="rec-analysis-body" id="rec-analysis-body"></div>`;
    renderInto(panel.querySelector("#rec-analysis-body"), content.markdown || "（没有内容）");
    return;
  }
  const reason = analysis.status === "canceled" ? "分析已取消" : (analysis.error || "分析失败");
  panel.innerHTML = `<div class="rec-analysis-empty">
    <strong>分析没成</strong><p>${escapeHtml(reason)}</p></div>`;
}

function startPolling(recordingId) {
  if (analysisTimer) return;
  const seq = analysisSeq;
  const tick = async () => {
    analysisTimer = null;
    if (!current || current.id !== recordingId || seq !== analysisSeq) return;
    try {
      const data = await api.get(`/api/recordings/${recordingId}/analysis`);
      if (!current || current.id !== recordingId) return;
      current.analysis = data.analysis || null;
      renderAnalysis(current);
    } catch (error) {
      toast(error.message);
    }
  };
  analysisTimer = setTimeout(tick, 1500);
}

async function analyze(force = false) {
  if (!current) return;
  const id = current.id;
  try {
    const data = await api.post(`/api/recordings/${id}/analyze${force ? "?force=true" : ""}`);
    if (!current || current.id !== id) return;
    if (data.cached && data.status === "done") {
      const fresh = await api.get(`/api/recordings/${id}/analysis`);
      current.analysis = fresh.analysis || null;
    } else {
      current.analysis = { id: data.id, status: data.status || "pending" };
    }
    renderAnalysis(current);
  } catch (error) {
    toast(error.message);
  }
}

async function quizFrom() {
  if (!current) return;
  let materialId = current.analysis?.content?.material_id || current.material_id || 0;
  if (!materialId) {
    try {
      const data = await api.post(`/api/recordings/${current.id}/material`);
      materialId = data.item?.id || 0;
      current.material_id = materialId;
    } catch (error) {
      toast(error.message);
      return;
    }
  }
  if (!materialId) {
    toast("这段还没有可出题的内容");
    return;
  }
  location.hash = `#/quiz?material=${materialId}`;
}

function stopTranscriptPolling() {
  if (transcriptTimer) {
    clearTimeout(transcriptTimer);
    transcriptTimer = null;
  }
  transcriptSeq += 1;
}

function startTranscriptPolling(recordingId) {
  if (transcriptTimer) return;
  const seq = transcriptSeq;
  let tries = 0;
  const tick = async () => {
    transcriptTimer = null;
    if (!current || current.id !== recordingId || seq !== transcriptSeq) return;
    tries += 1;
    try {
      const data = await api.get(`/api/recordings/${recordingId}`);
      if (!current || current.id !== recordingId) return;
      if ((data.transcripts || []).length > 0 || data.chars > 0) {
        current.transcripts = data.transcripts || [];
        current.chars = data.chars || 0;
        const box = nodes.detailBody.querySelector(".rec-transcript");
        if (box) box.innerHTML = transcriptRows(current.transcripts);
        return;
      }
      if (tries < 24) transcriptTimer = setTimeout(tick, 2500);
    } catch (error) {
      if (tries < 24) transcriptTimer = setTimeout(tick, 4000);
    }
  };
  transcriptTimer = setTimeout(tick, 1500);
}

function renderDetail(item) {
  stopPolling();
  stopTranscriptPolling();
  current = item;
  nodes.detail.hidden = false;
  nodes.title.textContent = item.title;
  const player = item.video_url
    ? `<video class="rec-video" controls preload="metadata"
         src="${escapeHtml(item.video_url)}"${item.thumb_url
           ? ` poster="${escapeHtml(item.thumb_url)}"` : ""}></video>`
    : `<div class="empty"><strong>视频文件不在</strong>
       可能被移走或删除了；转写和资料还在。</div>`;
  nodes.detailBody.innerHTML = `${player}
    <div class="rec-detail-meta">${escapeHtml(item.started_at)} · ${secondsText(item.duration)}
      · ${bytesText(item.video_bytes)} · 转写 ${item.chars} 字${
        item.ocr_chars ? ` · 幻灯片文字 ${item.ocr_chars} 字` : ""}</div>
    <div class="rec-actions">
      <button class="btn" type="button" id="rec-ask">问这段</button>
      <button class="btn" type="button" id="rec-quiz">出题</button>
      <button class="btn btn-primary" type="button" id="rec-analyze">分析这段</button>
      <button class="btn" type="button" id="rec-open-folder">打开文件夹</button>
      <button class="btn" type="button" id="rec-save">存为资料</button>
      <button class="btn danger" type="button" id="rec-delete">删除这段</button>
    </div>
    <section class="rec-ai" id="rec-ai">
      <div class="rec-ai-head"><strong>问一问 · 这段录像</strong>
        <span class="rec-ai-head-actions">
          <button class="rec-ai-link" type="button" id="rec-ai-new">新对话</button>
          <button class="rec-ai-link" type="button" id="rec-ai-open">在问一问里打开</button>
        </span></div>
      <div class="rec-ai-history" id="rec-ai-history" hidden></div>
      <div class="rec-ai-thread" id="rec-ai-thread" hidden></div>
      <div class="rec-ai-row">
        <textarea id="rec-ai-input" rows="2"
          placeholder="这段里……是什么意思？Enter 发送，Shift+Enter 换行"></textarea>
        <button class="btn btn-primary" type="button" id="rec-ai-send">问</button>
        <button class="btn" type="button" id="rec-ai-stop" hidden>停止</button>
      </div>
    </section>
    <section class="rec-analysis" id="rec-analysis"></section>
    <div class="rec-transcript">${transcriptRows(item.transcripts || [], !(item.transcripts || []).length)}</div>
    ${slideGrid(item.slides || [])}`;
  video = nodes.detailBody.querySelector("video");
  nodes.detailBody.querySelector("#rec-ask")?.addEventListener("click", () => aiPanel?.focus());
  nodes.detailBody.querySelector("#rec-quiz")?.addEventListener("click", quizFrom);
  nodes.detailBody.querySelector("#rec-analyze")?.addEventListener("click", () => {
    analyze(current?.analysis?.status === "done");
  });
  nodes.detailBody.querySelector("#rec-open-folder")?.addEventListener("click", openFolder);
  nodes.detailBody.querySelector("#rec-save")?.addEventListener("click", saveMaterial);
  nodes.detailBody.querySelector("#rec-delete")?.addEventListener("click", deleteRecording);
  nodes.detailBody.querySelectorAll(".rec-time").forEach((button) => {
    button.addEventListener("click", () => {
      if (!video) return;
      video.currentTime = Number(button.dataset.at) || 0;
      video.play().catch(() => {});
    });
  });
  if (!(item.transcripts || []).length) startTranscriptPolling(item.id);
  renderAnalysis(item);
  aiPanel?.reset(item.id);
  nodes.detail.scrollIntoView({ behavior: "smooth", block: "start" });
}

function closeDetail() {
  stopPolling();
  stopTranscriptPolling();
  aiPanel?.dispose();
  if (video) {
    video.pause();
    video = null;
  }
  current = null;
  nodes.detail.hidden = true;
  nodes.detailBody.innerHTML = "";
}

async function load() {
  try {
    const query = nodes.search.value.trim();
    const data = await api.get(`/api/recordings?q=${encodeURIComponent(query)}&limit=100`);
    items = data.items || [];
    renderList();
    renderStats(data.totals || {});
  } catch (error) {
    nodes.list.innerHTML = `<div class="empty"><strong>读录像失败</strong>${escapeHtml(error.message)}</div>`;
  }
}

async function openRoot() {
  try {
    const data = await api.post("/api/recordings/open-root");
    toast(data.message || "已打开录像文件夹");
  } catch (error) {
    toast(error.message);
  }
}

async function openFolder() {
  if (!current) return;
  try {
    const data = await api.post(`/api/recordings/${current.id}/open-folder`);
    toast(data.message || "已打开文件夹");
  } catch (error) {
    toast(error.message);
  }
}

async function saveMaterial() {
  if (!current) return;
  try {
    const data = await api.post(`/api/recordings/${current.id}/material`);
    current.material_id = data.item?.id || current.material_id || 0;
    toast(data.created ? `已存为资料：${data.item?.title || ""}` : "这段已经存过资料了");
  } catch (error) {
    toast(error.message);
  }
}

async function deleteRecording() {
  if (!current) return;
  const ok = window.confirm("删除这段录像、转写、幻灯片和分析？\n已存的资料不会删。");
  if (!ok) return;
  try {
    await api.del(`/api/recordings/${current.id}`);
    toast("已删除这段录像");
    closeDetail();
    await load();
  } catch (error) {
    toast(error.message);
  }
}

export async function mount(ctx) {
  ctx.setSub("主屏 + 系统声音录成 MP4；转写、幻灯片和分析跟视频放在同一个文件夹");
  ctx.setActions('<button class="btn btn-primary" type="button" id="rec-start">开始录像</button>'
    + '<a class="btn" href="#/today">回今日</a>');
  nodes = {
    stats: ctx.root.querySelector("#rec-stats"),
    list: ctx.root.querySelector("#rec-list"),
    count: ctx.root.querySelector("#rec-count"),
    search: ctx.root.querySelector("#rec-search"),
    refresh: ctx.root.querySelector("#rec-refresh"),
    folder: ctx.root.querySelector("#rec-folder"),
    detail: ctx.root.querySelector("#rec-detail"),
    detailBody: ctx.root.querySelector("#rec-detail-body"),
    title: ctx.root.querySelector("#rec-title"),
    close: ctx.root.querySelector("#rec-close"),
  };
  items = [];
  current = null;
  video = null;
  recordControl?.dispose();
  recordControl = null;
  aiPanel?.dispose();
  aiPanel = null;
  stopPolling();
  aiPanel = createAIPanel({ detailBody: nodes.detailBody });
  nodes.refresh.addEventListener("click", load);
  nodes.folder.addEventListener("click", openRoot);
  nodes.close.addEventListener("click", closeDetail);
  nodes.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 220);
  });
  nodes.list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-open]");
    if (!button) return;
    const id = Number(button.dataset.open);
    const item = items.find((one) => one.id === id);
    if (!item) return;
    api.get(`/api/recordings/${id}`)
      .then((detail) => renderDetail(detail))
      .catch((error) => toast(error.message));
  });
  await load();
  recordControl = createRecordControl({
    button: document.getElementById("rec-start"),
    formatDuration: secondsText,
    onFinished: load,
  });
  await recordControl.refresh();
  const sessionId = Number(ctx.query?.get("session") || 0);
  if (sessionId) {
    try {
      const detail = await api.get(`/api/recordings/${sessionId}`);
      renderDetail(detail);
    } catch (error) {
      toast(error.message);
    }
  }
}

export function unmount() {
  clearTimeout(searchTimer);
  recordControl?.dispose();
  recordControl = null;
  closeDetail();
}
