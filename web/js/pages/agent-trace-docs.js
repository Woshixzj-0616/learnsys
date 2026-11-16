// 「调用路径」页的字段字典：原始事件里的每个键是什么意思。
// 单独一份，渲染和页面逻辑都不在这里。
import { escapeHtml } from "../ui.js";

export const EVENT_DOCS = {
  gates: "开轮判断：这一轮该摆哪些工具、走哪条路。",
  ask: "用户这一轮的原话和输入。",
  ctx: "给模型的上下文有多大（字符数，不是 token）。",
  llm: "一次模型调用。",
  tool: "一次工具调用。",
  nudge: "打回：模型想作答，但代码认为还缺东西，让它重来一轮。",
  audit: "规则审核：答案和证据对不上的地方。",
  audit_llm: "模型审核：语义层的问题（编造 / 过度声称）。",
  answer: "最终正文。",
  spans: "耗时分解。",
  end: "这一轮怎么结束的。",
  direct: "轻量档直接流式作答（页面补的说明，不是原始 trace 事件）。",
};

export const FIELD_DOCS = {
  e: "事件类型。",
  at: "从这一轮请求开始算，第几毫秒。",
  // gates
  need_search: "这一题必须联网核实。",
  plan_like: "像不像计划类问题。",
  wants_plan: "这一轮要排程。",
  wants_rules: "这一轮要按名读硬约束（闭馆 / 预约 / 放号）。",
  wants_ledger: "这一轮要记账 / 分账。",
  wants_requirement: "这一轮要记长期要求。",
  wants_interest: "这一轮在说兴趣画像。",
  wants_sessions: "这一轮要翻历史会话。",
  wants_session_delete: "这一轮要删历史会话。",
  interest_undo: "这一轮在撤销兴趣。",
  model_plan: "模型判断：要不要排程。",
  model_ledger: "模型判断：要不要记账。",
  model_requirement: "模型判断：要不要记长期要求。",
  model_interest: "模型判断：是不是兴趣。",
  model_rules: "模型判断：要不要读硬约束。",
  model_direct: "模型判断：能不能直接答、不用查。",
  intent_judged: "这一轮到底问没问模型做意图判断。",
  direct: "轻量档：不挂工具、一轮流式答完。",
  tools_always: "诊断开关：工具是不是常驻。",
  state_gates: "分档闸门（指代否定那半）开没开。",
  // ask
  q: "用户这一轮的原话。",
  has_trip: "用户手上有没有行程。",
  view: "有没有带地图视图状态。",
  vision: "有没有带照片感知结果。",
  // ctx
  round: "第几轮（0 = 开轮，final = 最后流式）。",
  base: "提示词底表字数。",
  notes: "按需注入的提示词段落字数。",
  trip: "行程段字数。",
  prefs: "偏好 / 记忆段字数。",
  tree: "界面树段字数。",
  prefetch: "预取段字数。",
  recent: "最近历史条数 / 字数。",
  summary: "滚动摘要字数。",
  tool: "工具结果字数。",
  schema: "工具 schema 字数。",
  system: "整个 system 段字数。",
  history: "历史消息字数。",
  tools: "工具表字数。",
  total: "上下文总字数。",
  msgs: "消息条数。",
  parts_sum: "分项相加的总和（用来对账）。",
  // llm
  n: "第几次模型调用。",
  ms: "耗时（毫秒）。",
  model: "模型名。",
  finish: "结束原因：tool_calls / stop / length。",
  tin: "输入 token 数。",
  tout: "输出 token 数。",
  hit: "前缀缓存命中的 token 数。",
  miss: "前缀缓存没命中的 token 数。",
  clen: "这一轮模型写的正文长度。",
  alen: "答案长度（某些路径用）。",
  think: "模型思考正文（可能很长，原始 JSON 里有全文）。",
  // tool
  name: "工具名。",
  kind: "工具类别：tool / rules / plan / ledger / requirement / interest / session / gui / uitree。",
  ok: "这次调用成没成。",
  args: "模型填的入参（JSON 文本）。",
  res: "回执摘要：多少字 / 来自哪些域。",
  why: "失败原因。",
  // audit
  faults: "规则审核发现几处问题。",
  issues: "模型审核发现几处问题。",
  // answer
  chars: "字数。",
  answer: "正文全文。",
  // spans
  total_ms: "这一轮总耗时。",
  prefetch_ms: "预取耗时。",
  intent_ms: "意图判断耗时。",
  llm_ms: "模型调用耗时合计。",
  tools_ms: "工具调用耗时合计。",
  plan_ms: "排程补数耗时。",
  final_ms: "收尾流式作答耗时。",
  audit_ms: "审核耗时。",
  // end
  ended: "结束方式：ok / direct / budget / deadline / forced-wrapup / failed。",
  rounds: "跑了几轮模型。",
  calls: "调了几次工具。",
  repeats: "同参重复调用几次。",
  tools: "这一轮调过哪些工具。",
  chain: "一行链路：问 → 第几轮 → 工具 → 答。",
};

export function resolveKey(key) {
  if (FIELD_DOCS[key]) return key;
  // obs 会把字段名截到 16 字：wants_requiremen -> wants_requirement
  const full = Object.keys(FIELD_DOCS).find((name) => name.startsWith(key) && name !== key);
  return full || key;
}

export function formatValue(value) {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "是" : "否";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (text.length > 180) return text.slice(0, 180) + `…（共 ${text.length} 字）`;
  return text;
}

export function explainEvent(ev) {
  const type = String(ev.e || "?");
  const rows = [];
  const push = (key, value) => {
    const full = resolveKey(key);
    rows.push({ key, full, value, doc: FIELD_DOCS[full] || "未登记字段，原样显示。" });
  };
  push("e", type);
  push("at", ev.at);
  Object.keys(ev).forEach((key) => {
    if (key !== "e" && key !== "at") push(key, ev[key]);
  });
  const body = rows.map((row) => {
    const value = typeof row.value === "boolean"
      ? `<span class="at-bool ${row.value ? "on" : "off"}">${row.value ? "是" : "否"}</span>`
      : escapeHtml(formatValue(row.value));
    const full = row.full !== row.key
      ? `<div class="at-raw-full">完整名：${escapeHtml(row.full)}</div>` : "";
    return `<tr><td><code>${escapeHtml(row.key)}</code>${full}</td>
      <td>${value}</td><td>${escapeHtml(row.doc)}</td></tr>`;
  }).join("");
  return `<div class="at-raw">
    <div class="at-raw-head">${escapeHtml(type)} · ${escapeHtml(EVENT_DOCS[type] || "原始事件")}</div>
    <table class="at-raw-table">
      <thead><tr><th>字段</th><th>值</th><th>意思</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
    <details class="at-raw-json"><summary>原始 JSON（未加工）</summary>
      <pre>${escapeHtml(JSON.stringify(ev, null, 2))}</pre>
    </details>
  </div>`;
}
