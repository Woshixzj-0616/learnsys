// 复盘：读今日记录 → 流式生成一张「今天学了什么」的卡片，并写一条 review 事件。
import { api, streamChat } from "../api.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, toast } from "../ui.js";

let data = null;
let running = false;
let reportSent = false;

export async function mount(ctx) {
  ctx.setSub("把今天的记录收成一张能带走的卡片");
  ctx.setActions('<a class="btn" href="#/ask">去问一问</a>');
  const root = ctx.root;
  const runBtn = root.querySelector("#review-run");
  try {
    data = await api.get("/api/study/today");
  } catch (error) {
    root.querySelector("#review-material").innerHTML =
      `<div class="empty">读不到今天的记录：${escapeHtml(error.message || error)}</div>`;
    runBtn.disabled = true;
    return;
  }
  renderStats(root, data.stats || {});
  renderMaterial(root, data);
  const hasData = (data.stats?.minutes || 0) > 0
    || (data.stats?.transcripts || 0) > 0
    || (data.stats?.asks || 0) > 0
    || (data.stats?.trainings || 0) > 0
    || (data.stats?.cet6 || 0) > 0
    || (data.summary_lines || []).length > 0;
  runBtn.disabled = !hasData;
  if (!hasData) {
    root.querySelector("#review-status").textContent =
      "今天还没有可复盘的记录 —— 先问几个问题、练一格或录一段课。";
    return;
  }
  runBtn.addEventListener("click", () => run(root, runBtn));
}

function renderStats(root, stats) {
  const items = [
    ["专注", `${Number(stats.minutes || 0).toFixed(0)} 分钟`],
    ["问答", `${stats.asks || 0} 条`],
    ["转写", `${stats.transcripts || 0} 段`],
    ["网工训练", `${stats.trainings || 0} 格`],
    ["六级断点", `${stats.cet6 || 0} 个`],
    ["资料", `${stats.materials || 0} 次`],
  ];
  root.querySelector("#review-stats").innerHTML = items.map(([label, value]) => `
    <div class="review-chip"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
}

function renderMaterial(root, payload) {
  const lines = payload.summary_lines || [];
  const asks = payload.asks || [];
  const transcript = payload.transcript || "";
  const material = root.querySelector("#review-material");
  material.innerHTML = `
    <div class="material-block">
      <h3>记录摘要</h3>
      ${lines.length
        ? `<ul class="material-list">${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
        : '<p class="hint">今天没有开过录制。</p>'}
    </div>
    <div class="material-block">
      <h3>今天问过的 <span class="hint">${asks.length} 条</span></h3>
      ${asks.length
        ? `<ul class="material-list">${asks.slice(0, 12).map((ask) => `
            <li><span class="material-time">${escapeHtml(String(ask.ts || "").slice(11, 16))}</span>
            ${escapeHtml(ask.question || "")}</li>`).join("")}</ul>`
        : '<p class="hint">今天还没有提问。</p>'}
    </div>
    ${transcript ? `<details class="material-transcript">
      <summary>课堂转写（${payload.transcript_chars || transcript.length} 字，点开看）</summary>
      <pre>${escapeHtml(transcript)}</pre>
    </details>` : ""}`;
}

async function run(root, button) {
  if (running || !data) return;
  running = true;
  button.disabled = true;
  button.textContent = "复盘中…";
  const result = root.querySelector("#review-result");
  const status = root.querySelector("#review-status");
  result.innerHTML = '<p class="hint">AI 正在读今天的记录…</p>';
  status.textContent = "";
  let text = "";
  let errorText = "";
  try {
    await streamChat({ message: data.review_prompt, mode: "explain",
      module: "review", internal: true }, (event) => {
      if (event.kind === "text") {
        text += event.text || "";
        renderInto(result, text);
        status.textContent = "正在写…";
      } else if (event.kind === "rewrite") {
        text = String(event.data?.text || text);
        renderInto(result, text);
        status.textContent = "已按自检结果重写";
      } else if (event.kind === "tool_start") {
        status.textContent = "在查本地记录…";
      } else if (event.kind === "done") {
        const finalText = String(event.data?.text || text || "");
        if (finalText) {
          text = finalText;
          renderInto(result, text);
        }
      } else if (event.kind === "error") {
        errorText = event.text || "模型没有回答";
      }
    });
    if (errorText) throw new Error(errorText);
    if (!text.trim()) throw new Error("模型没有返回内容");
    const first = !reportSent;
    if (first) {
      reportSent = true;
      await api.post("/api/events", {
        module: "review", kind: "report", title: "今日复盘",
        meta: { date: data.date, chars: text.length },
      }).catch(() => {});
    }
    status.textContent = first ? "复盘完成 · 学习点 +25" : "复盘完成（本次不再重复计点）";
    toast(first ? "复盘完成，学习点 +25" : "复盘完成", "ok");
    window.dispatchEvent(new CustomEvent("learnsys:refresh"));
  } catch (error) {
    result.innerHTML = `<p class="review-error">${escapeHtml(error.message || error)}</p>`;
    status.textContent = "没成功 —— 确认模型已配置、后台在运行后重试。";
  } finally {
    running = false;
    button.disabled = false;
    button.textContent = "重新复盘";
  }
}
