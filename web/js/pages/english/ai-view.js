// 六级 AI 抽屉的纯视图：只拼 DOM，不碰网络和状态。
import { renderInto } from "../../markdown.js";
import { escapeHtml, relative } from "../../ui.js";

export const SUGGESTS = {
  listening: ["这段在讲什么？", "这一句为什么听不出来？", "帮我总结本段的考点"],
  drill: ["这句为什么听不出来？", "帮我总结这段的考点", "这个漏听词怎么记？"],
  writing: ["这篇作文的立意怎么改？", "帮我把这句写得更地道", "我最大的写作问题是什么？"],
  translation: ["这句话怎么切分意群？", "这个术语怎么译更准？", "我的译文哪里不地道？"],
  review: ["这张卡为什么我总忘？", "帮我讲清楚这个错误", "再给我一个同类例句"],
  stats: ["我最大的错误在哪？", "接下来两周先练什么？", "帮我排一个复习计划"],
  daily: ["今天这几组短语怎么用？", "帮我用这个句型造句", "这些短语有什么区别？"],
};

export const FALLBACK_SUGGESTS = ["我现在最该练什么？", "帮我解释一下这个概念"];

export const PANEL_HTML = `
  <div class="cet6-ai-head">
    <div class="cet6-ai-title">
      <b>六级 AI</b><span class="cet6-ai-model" data-model>deepseek-flash</span>
    </div>
    <div class="cet6-ai-head-actions">
      <button type="button" data-ai="new">新对话</button>
      <button type="button" data-ai="close">收起</button>
    </div>
  </div>
  <div class="cet6-ai-tabs" role="tablist">
    <button type="button" data-ai-tab="chat" class="on" role="tab">对话</button>
    <button type="button" data-ai-tab="history" role="tab">历史</button>
  </div>
  <div class="cet6-ai-view" data-view="chat">
    <p class="cet6-ai-ctx" data-ctx>正在看你：六级训练</p>
    <div class="cet6-ai-messages" data-messages></div>
    <div class="cet6-ai-suggest" data-suggest></div>
    <div class="cet6-ai-input">
      <textarea data-input rows="2" placeholder="问点什么？Enter 发送，Shift+Enter 换行"></textarea>
      <button type="button" class="cet6-ai-send" data-ai="send">发送</button>
      <button type="button" class="cet6-ai-stop" data-ai="stop" hidden>停止</button>
    </div>
  </div>
  <div class="cet6-ai-view" data-view="history" hidden>
    <input type="search" class="cet6-ai-history-search" data-history-search
      placeholder="搜对话标题…" autocomplete="off">
    <div class="cet6-ai-history" data-history></div>
  </div>`;

/** 在页面根节点里建出圆圈、划词浮钮和抽屉，返回所有节点引用。 */
export function buildDom(host) {
  const fab = document.createElement("button");
  fab.type = "button";
  fab.className = "cet6-ai-fab";
  fab.title = "六级 AI（Ctrl+J）";
  fab.setAttribute("aria-expanded", "false");
  fab.textContent = "AI";

  const sel = document.createElement("button");
  sel.type = "button";
  sel.className = "cet6-ai-sel";
  sel.textContent = "问 AI";
  sel.hidden = true;

  const dock = document.createElement("aside");
  dock.className = "cet6-ai-dock";
  dock.hidden = true;
  dock.setAttribute("aria-label", "六级 AI 助手");
  dock.innerHTML = PANEL_HTML;
  host.append(fab, sel, dock);

  const q = (selector) => dock.querySelector(selector);
  return {
    fab, sel, dock,
    model: q("[data-model]"),
    ctx: q("[data-ctx]"),
    messages: q("[data-messages]"),
    suggest: q("[data-suggest]"),
    input: q("[data-input]"),
    send: q('[data-ai="send"]'),
    stop: q('[data-ai="stop"]'),
    chatView: q('[data-view="chat"]'),
    historyView: q('[data-view="history"]'),
    historySearch: q("[data-history-search]"),
    historyList: q("[data-history]"),
  };
}

export function renderWelcome(messages) {
  messages.innerHTML = `<div class="cet6-ai-welcome">
    <b>六级 AI</b>
    <p>直接问。会自动带上你正在练的题、作文、译文或复习卡。</p>
    <p class="hint">选中页面里的文字，还能把这句原文一起带过去问。</p>
  </div>`;
}

export function renderSuggest(box, rows) {
  box.innerHTML = rows.map((text) =>
    `<button type="button" data-suggest="${escapeHtml(text)}">${escapeHtml(text)}</button>`)
    .join("");
}

export function addMessage(messages, role, text) {
  const wrap = document.createElement("div");
  wrap.className = `cet6-ai-msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "cet6-ai-bubble";
  bubble.textContent = text || "";
  wrap.appendChild(bubble);
  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;
  return { wrap, bubble };
}

// 流式重绘：思考过程、工具轨迹、正文三块；正文走统一 Markdown 清洗。
export function paintBubble(bubble, state, isStreaming) {
  bubble.innerHTML = "";
  if (state.thinking) {
    const details = document.createElement("details");
    details.className = "cet6-ai-think";
    if (isStreaming) details.open = true;
    details.innerHTML = '<summary>思考过程</summary><div class="cet6-ai-think-body"></div>';
    renderInto(details.querySelector(".cet6-ai-think-body"), state.thinking);
    bubble.appendChild(details);
  }
  if (state.trace.length) {
    const tools = document.createElement("div");
    tools.className = "cet6-ai-tools";
    tools.innerHTML = state.trace.map((row) => `<span>${escapeHtml(row)}</span>`).join("");
    bubble.appendChild(tools);
  }
  const body = document.createElement("div");
  body.className = "cet6-ai-text";
  if (state.error) {
    body.classList.add("err");
    body.textContent = `出错了：${state.error}`;
  } else if (state.answer) {
    renderInto(body, state.answer);
  } else {
    body.textContent = isStreaming ? "正在思考…" : "（没有返回内容）";
  }
  bubble.appendChild(body);
  const scroller = bubble.closest(".cet6-ai-messages");
  if (scroller) scroller.scrollTop = scroller.scrollHeight;
}

export function historyLabel(row) {
  const stamp = String(row.updated_at || "");
  return stamp ? relative(stamp) : "";
}

export function renderHistory(list, rows, query, currentId) {
  const text = String(query || "").trim().toLowerCase();
  const filtered = rows.filter((row) =>
    !text || String(row.title || "").toLowerCase().includes(text));
  if (!filtered.length) {
    list.innerHTML = `<p class="cet6-ai-status">${
      rows.length ? "没有匹配的对话。" : "还没有对话。问一句就会出现在这里。"}</p>`;
    return;
  }
  list.innerHTML = filtered.map((row) => {
    const current = Number(row.id) === Number(currentId);
    return `<button type="button" class="cet6-ai-history-item${current ? " on" : ""}"
        data-conv="${Number(row.id)}">
      <span class="t">${escapeHtml(row.title || "新对话")}</span>
      <span class="m">${escapeHtml(historyLabel(row))} · ${Number(row.messages || 0)} 条${
        current ? " · 当前" : ""}</span>
    </button>`;
  }).join("");
}

export function status(text) {
  return `<p class="cet6-ai-status">${escapeHtml(text)}</p>`;
}
