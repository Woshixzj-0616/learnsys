// 「调用路径」页的渲染：列表行、路径图、时间线、字段解释的挂载点。
// 不碰网络、不碰页面状态；输入是 trace 数据，输出是 HTML 字符串。
import { escapeHtml } from "../ui.js";
import { explainEvent } from "./agent-trace-docs.js";

export function fmt(ms) {
  if (ms == null || ms === "") return "?";
  const n = Number(ms);
  if (!Number.isFinite(n)) return "?";
  return n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${n}ms`;
}

function find(events, name) {
  return (events || []).filter((e) => e && e.e === name);
}

function one(events, name) {
  const rows = find(events, name);
  return rows.length ? rows[0] : null;
}

const GATE_KEYS = [
  "need_search", "plan_like", "wants_plan", "wants_rules", "wants_ledger",
  "wants_requirement", "wants_interest", "wants_sessions", "direct",
  "intent_judged", "model_plan", "model_direct", "state_gates",
];

export function rowHtml(item, currentId) {
  const s = item.summary || {};
  const ok = s.ended === "ok";
  const tag = ok ? "ok" : (s.ended ? "bad" : "");
  const direct = s.ended === "direct" && !s.llm_calls;
  const llmCount = (s.llm_calls || 0) + (direct ? 1 : 0);
  return `<button class="at-row${item.trace_id === currentId ? " on" : ""}" data-id="${escapeHtml(item.trace_id)}">
    <div class="at-r1"><span>${escapeHtml(item.at)}</span><span>${fmt(item.ms)}</span></div>
    <div class="at-q">${escapeHtml(s.question || "（没有提取到问题）")}</div>
    <div class="at-r2">
      <span class="at-tag ${tag}">${escapeHtml(s.ended || "未知")}</span>
      <span class="at-tag">LLM ${llmCount}${direct ? "（直接）" : ""}</span>
      <span class="at-tag">工具 ${s.tool_calls || 0}</span>
      <span class="at-tag">${s.chars || 0} 字</span>
    </div>
  </button>`;
}

export function pathHtml(events) {
  const nodes = [["用户", "一句话", ""], ["开轮", "意图 / 闸门", "gates"]];
  const llm = find(events, "llm");
  (events || []).forEach((e) => {
    if (e.e === "llm") nodes.push([`LLM #${e.n}`, fmt(e.ms), "llm"]);
    if (e.e === "tool") nodes.push([e.name, fmt(e.ms), "tool"]);
    if (e.e === "nudge") nodes.push(["打回", e.name || "", "nudge"]);
  });
  if (!llm.length) {
    const spans = one(events, "spans") || {};
    const end = one(events, "end") || {};
    if (end.ended === "direct") {
      nodes.push(["LLM", `直接流式 · ${fmt(spans.final_ms || 0)}`, "llm"]);
    }
  }
  const answer = one(events, "answer") || {};
  nodes.push(["审核", "规则 + 模型", ""], ["回答", `${answer.chars || 0} 字`, "answer"]);
  return `<div class="at-path">${nodes.map(([t, n, c], i) =>
    `${i ? `<div class="at-arrow">→</div>` : ""}<div class="at-node ${c}"><div class="n">${escapeHtml(n)}</div><div class="t">${escapeHtml(t)}</div></div>`).join("")}</div>`;
}

function chips(ev) {
  const on = GATE_KEYS.filter((key) => ev[key]);
  if (!on.length) return `<div class="at-chips"><span class="at-chip">全部未命中</span></div>`;
  return `<div class="at-chips">${on.map((key) => `<span class="at-chip on">${escapeHtml(key)}</span>`).join("")}</div>`;
}

function card(ev) {
  const time = `<span class="at-time">${ev.at == null ? "?" : ev.at + "ms"}</span>`;
  if (ev.e === "gates") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">开轮判断</span><span class="at-desc">这一轮该摆哪些工具</span></div>${chips(ev)}</div>`;
  }
  if (ev.e === "ask") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">用户原话</span><span class="at-desc">手上有行程=${ev.has_trip ? "是" : "否"}</span></div><div class="at-answer">${escapeHtml(ev.q || "")}</div></div>`;
  }
  if (ev.e === "ctx") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">上下文计量</span><span class="at-desc">round ${ev.round}</span></div><div class="at-desc">总 ${ev.total} 字 · system ${ev.system} · tools ${ev.tools} · history ${ev.history}</div></div>`;
  }
  if (ev.e === "llm") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">模型第 ${ev.n} 次</span><span class="at-desc">${fmt(ev.ms)} · ${escapeHtml(ev.model || "")} · finish=${escapeHtml(ev.finish || "")}</span></div><div class="at-desc">输入 ${ev.tin} tok（缓存命中 ${ev.hit}）· 输出 ${ev.tout} tok</div></div>`;
  }
  if (ev.e === "direct") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">直接流式作答</span><span class="at-desc">${fmt(ev.ms)} · ${ev.chars || 0} 字</span></div><div class="at-desc">轻量档：不挂工具、一轮流式答完；trace 里没有单独的 llm 事件，这里按 final 段补一条。</div></div>`;
  }
  if (ev.e === "tool") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">${escapeHtml(ev.name)}</span><span class="at-desc">kind=${escapeHtml(ev.kind || "")} · ${ev.ok ? "成功" : "失败"} · ${fmt(ev.ms)}</span></div><div class="at-args">入参：${escapeHtml(ev.args || "")}${ev.res ? `\n回执：${escapeHtml(ev.res)}` : ""}${ev.why ? `\n原因：${escapeHtml(ev.why)}` : ""}</div></div>`;
  }
  if (ev.e === "nudge") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">打回</span><span class="at-desc">${escapeHtml(ev.name || ev.kind || "")}</span></div><div class="at-desc">模型想作答，但代码认为还缺东西，让它重来一轮。</div></div>`;
  }
  if (ev.e === "audit") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">规则审核</span><span class="at-desc">${ev.faults || 0} 处问题</span></div></div>`;
  }
  if (ev.e === "audit_llm") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">模型审核</span><span class="at-desc">${ev.issues || 0} 处问题</span></div></div>`;
  }
  if (ev.e === "answer") {
    const text = String(ev.answer || "");
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">最终答案</span><span class="at-desc">${ev.chars || 0} 字</span></div><div class="at-answer">${escapeHtml(text.slice(0, 300))}${text.length > 300 ? "…" : ""}</div></div>`;
  }
  if (ev.e === "spans") {
    const rows = [["预取", ev.prefetch_ms], ["意图", ev.intent_ms], ["模型", ev.llm_ms], ["工具", ev.tools_ms], ["收尾", ev.final_ms]];
    const max = Math.max(1, ...rows.map((r) => Number(r[1]) || 0));
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">耗时分解</span><span class="at-desc">总 ${fmt(ev.total_ms)}</span></div><div class="at-bars">${rows.map(([k, v]) => `<div class="at-bar-row"><span>${k}</span><div class="at-track"><div class="at-fill" style="width:${Math.round((Number(v) || 0) / max * 100)}%"></div></div><span class="at-val">${fmt(v || 0)}</span></div>`).join("")}</div></div>`;
  }
  if (ev.e === "end") {
    return `<div class="at-card"><div class="at-h">${time}<span class="at-name">结束</span><span class="at-desc">${escapeHtml(ev.ended || "")} · ${ev.rounds || 0} 轮 / ${ev.calls || 0} 次工具 · ${ev.chars || 0} 字</span></div><div class="at-desc">${escapeHtml(ev.chain || "")}</div></div>`;
  }
  return `<div class="at-card"><div class="at-h">${time}<span class="at-name">${escapeHtml(ev.e || "?")}</span></div></div>`;
}

export function summaryHtml(data) {
  const s = data.summary || {};
  // 轻量档（direct）的流式作答没有单独 llm 事件，但确实调了一次模型。
  const directStream = s.ended === "direct" && !s.llm_calls;
  const modelCalls = (s.llm_calls || 0) + (directStream ? 1 : 0);
  const items = [
    ["总耗时", fmt(s.total_ms || data.ms), ""],
    ["模型调用", modelCalls, directStream ? "次（含直接流式）" : "次"],
    ["工具调用", s.tool_calls || 0, "次"],
    ["打回", s.nudges || 0, "次"],
    ["答案长度", s.chars || 0, "字"],
  ];
  return `<div class="at-summary">${items.map(([k, v, u]) => `<div class="at-stat"><div class="k">${k}</div><div class="v">${v}<span class="u">${u}</span></div></div>`).join("")}</div>`;
}

export function timelineHtml(events, showCtx) {
  const rows = (events || []).filter((e) => showCtx || e.e !== "ctx");
  return rows.map((ev) => {
    const cls = ev.e === "audit_llm" ? "audit" : ev.e;
    return `<li class="at-ev ${escapeHtml(cls)}">${card(ev)}<details><summary>原始事件 + 字段解释</summary>${explainEvent(ev)}</details></li>`;
  }).join("");
}

export function detailEvents(events) {
  // 轻量档的流式作答没有 llm 事件：补一条「直接流式」，否则时间线像没调模型。
  const end = one(events, "end") || {};
  const llm = find(events, "llm");
  if (end.ended !== "direct" || llm.length) return events;
  const spans = one(events, "spans") || {};
  const answer = one(events, "answer") || {};
  const index = (events || []).findIndex((e) => e.e === "ask");
  const synthetic = { e: "direct", at: spans.at || end.at, ms: spans.final_ms || 0,
                      chars: answer.chars || 0, synthetic: true };
  const out = (events || []).slice();
  out.splice(index >= 0 ? index + 1 : out.length, 0, synthetic);
  return out;
}
