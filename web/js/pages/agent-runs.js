// 运行记录：一份 agent_runs 流水的面板（耗时 / token / 工具 / 成本 / 异常）。
import { api } from "../api.js";
import { escapeHtml, relative, toast } from "../ui.js";

const TOOL_NAMES = {
  search_records: "查本地记录",
  today_summary: "看今日概览",
  recent_wrong_items: "查错题本",
  read_attachment: "读文档",
  ocr_image: "OCR 看图",
  search_materials: "搜资料库",
  read_material: "读资料",
  get_cet6_context: "读六级进度",
  make_plan: "列计划",
  save_wrongbook: "收错题",
  save_memory: "记长期偏好",
  forget_memory: "忘掉记忆",
  save_material_note: "存资料笔记",
  write_study_file: "写学习档案",
  run_code: "运行代码",
};

const state = {
  mounted: false,
  days: Number(localStorage.getItem("learnsys_run_days") || 7),
  data: null,
  detailCache: new Map(),
};

let dom = {};
let ctxRef = null;

export async function mount(ctx) {
  ctxRef = ctx;
  state.mounted = true;
  state.detailCache.clear();
  dom = {
    stats: ctx.root.querySelector("#run-stats"),
    tools: ctx.root.querySelector("#run-tools"),
    toolNote: ctx.root.querySelector("#run-tool-note"),
    anomalies: ctx.root.querySelector("#run-anomalies"),
    recent: ctx.root.querySelector("#run-recent"),
    days: ctx.root.querySelector("#run-days"),
    refresh: ctx.root.querySelector("#run-refresh"),
  };
  dom.days.value = String(state.days);
  dom.days.addEventListener("change", () => {
    state.days = Number(dom.days.value) || 0;
    localStorage.setItem("learnsys_run_days", String(state.days));
    load();
  });
  dom.refresh.addEventListener("click", load);
  dom.recent.addEventListener("click", onRecentClick);
  await load();
}

export function unmount() {
  state.mounted = false;
}

async function load() {
  dom.stats.innerHTML = '<div class="review-chip"><span>正在读流水…</span><strong>—</strong></div>';
  try {
    const data = await api.get(`/api/agent/stats?days=${state.days}&limit=200`);
    if (!state.mounted) return;
    state.data = data;
    renderStats(data);
    renderTools(data);
    renderAnomalies(data);
    renderRecent(data);
    ctxRef?.setSub(`最近 ${data.runs} 次运行 · ${data.days ? data.days + " 天" : "全部"}`);
  } catch (error) {
    toast(error.message || "运行流水没读出来", "err");
    dom.stats.innerHTML = `<div class="empty">${escapeHtml(error.message || error)}</div>`;
  }
}

function fmtMs(value) {
  const ms = Number(value || 0);
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function fmtNum(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function fmtCost(value, currency) {
  const amount = Number(value || 0);
  if (!amount) return "—";
  return `${amount.toFixed(4)} ${currency || ""}`.trim();
}

function chip(label, value, hint = "") {
  return `<div class="review-chip"${hint ? ` title="${escapeHtml(hint)}"` : ""}>
    <span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function renderStats(data) {
  const totals = data.totals || {};
  const cost = totals.price_configured
    ? fmtCost(totals.cost, totals.currency)
    : "未配置单价";
  dom.stats.innerHTML = [
    chip("运行", `${data.runs} 次`),
    chip("首 token 平均", fmtMs(totals.first_ms_avg)),
    chip("总耗时平均", fmtMs(totals.total_ms_avg), `P95 ${fmtMs(totals.total_ms_p95)}`),
    chip("Tokens", fmtNum(totals.total_tokens),
      `输入 ${fmtNum(totals.prompt_tokens)} / 输出 ${fmtNum(totals.completion_tokens)} / 缓存命中 ${fmtNum(totals.cache_read_tokens)}`),
    chip("估算成本", cost, totals.price_configured ? "按设置里的单价估算" : "到 设置 → 成本估算 填单价"),
    chip("异常", `${data.errors} 次`),
  ].join("");
}

function renderTools(data) {
  const items = data.by_tool || [];
  dom.toolNote.textContent = items.length ? `共 ${items.length} 种工具` : "";
  if (!items.length) {
    dom.tools.innerHTML = '<div class="empty">这段时间还没有工具调用。</div>';
    return;
  }
  dom.tools.innerHTML = `<table class="runs-table runs-tools-table">
    <thead><tr><th>工具</th><th>调用</th><th>失败</th><th>平均耗时</th></tr></thead>
    <tbody>${items.map((item) => `
      <tr>
        <td>${escapeHtml(TOOL_NAMES[item.name] || item.name)}</td>
        <td>${fmtNum(item.calls)}</td>
        <td class="${item.failures ? "runs-bad" : ""}">${fmtNum(item.failures)}</td>
        <td>${fmtMs(item.avg_ms)}</td>
      </tr>`).join("")}</tbody></table>`;
}

function renderAnomalies(data) {
  const items = data.anomalies || [];
  if (!items.length) {
    dom.anomalies.innerHTML = '<div class="empty">这段时间没有异常，挺稳。</div>';
    return;
  }
  dom.anomalies.innerHTML = items.map((item) => `
    <div class="run-anomaly">
      <div class="run-anomaly-head">
        <strong>${escapeHtml(item.question || "（无问题）")}</strong>
        <span>${escapeHtml(relative(item.started_at))}</span>
      </div>
      <ul>${(item.issues || []).map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>
      ${item.conversation_id ? `<a class="btn" href="#/ask/${item.conversation_id}">打开会话</a>` : ""}
    </div>`).join("");
}

function statusOf(run) {
  if (run.error) return { label: "出错", cls: "runs-bad" };
  if (Number(run.error_count || 0) > 0) return { label: "有工具失败", cls: "runs-warn" };
  if (run.check_ok === false) return { label: "自检未过", cls: "runs-warn" };
  return { label: "正常", cls: "runs-ok" };
}

function renderRecent(data) {
  const items = data.recent || [];
  if (!items.length) {
    dom.recent.innerHTML = '<tr><td colspan="9" class="empty">这段时间还没有运行记录。</td></tr>';
    return;
  }
  dom.recent.innerHTML = items.map((run) => {
    const status = statusOf(run);
    return `<tr class="run-row" data-run="${escapeHtml(run.id)}">
      <td>${escapeHtml(relative(run.started_at))}</td>
      <td class="run-question">${escapeHtml(run.question || "（无问题）")}</td>
      <td>${escapeHtml(run.model || "—")}</td>
      <td>${fmtMs(run.first_ms)}</td>
      <td>${fmtMs(run.total_ms)}</td>
      <td>${fmtNum(run.tool_count)} 次工具 / ${run.model_calls ? `${fmtNum(run.model_calls)} 次模型` : "模型未记录"}</td>
      <td>${fmtNum(run.tokens)}</td>
      <td>${fmtCost(run.cost, run.currency)}</td>
      <td class="${status.cls}">${status.label}</td>
    </tr>
    <tr class="run-detail" data-detail="${escapeHtml(run.id)}" hidden><td colspan="9"></td></tr>`;
  }).join("");
}

async function onRecentClick(event) {
  const row = event.target.closest(".run-row");
  if (!row) return;
  const id = row.dataset.run;
  const detail = dom.recent.querySelector(`[data-detail="${CSS.escape(id)}"]`);
  if (!detail) return;
  if (!detail.hidden) {
    detail.hidden = true;
    return;
  }
  detail.hidden = false;
  const cell = detail.querySelector("td");
  cell.innerHTML = '<div class="hint">正在读逐事件回放…</div>';
  try {
    let run = state.detailCache.get(id);
    if (!run) {
      run = await api.get(`/api/agent/runs/${encodeURIComponent(id)}`);
      state.detailCache.set(id, run);
    }
    cell.innerHTML = renderTrace(run);
  } catch (error) {
    cell.innerHTML = `<div class="hint">${escapeHtml(error.message || "回放没读出来")}</div>`;
  }
}

function renderTrace(run) {
  const lines = [];
  for (const item of run.trace || []) {
    const data = item.data || {};
    if (item.kind === "route") {
      const actual = `${data.tier || "—"} · ${data.model || "—"}${data.thinking ? " · 思考" : ""}`;
      const rec = data.recommended
        ? ` → 建议 ${data.recommended.tier} · ${data.recommended.model}`
          + `${data.recommended.thinking ? " · 思考" : ""}（${data.recommended.reason || ""}）`
        : "";
      lines.push(`<div class="run-line"><b>路由</b> ${escapeHtml(actual + rec)}</div>`);
    } else if (item.kind === "plan") {
      lines.push(`<div class="run-line"><b>计划</b> ${(data.steps || []).map(
        (step, index) => `${index + 1}. ${escapeHtml(step.title || "")}`).join("；")}</div>`);
    } else if (item.kind === "tool_start") {
      const input = data.input && data.input["摘要"]
        ? data.input["摘要"] : "";
      lines.push(`<div class="run-line"><b>调用</b> ${escapeHtml(TOOL_NAMES[data.name] || data.name || "")}`
        + `${input ? ` · ${escapeHtml(input)}` : ""}</div>`);
    } else if (item.kind === "tool_end") {
      lines.push(`<div class="run-line ${data.ok === false ? "bad" : ""}"><b>${data.ok === false ? "失败" : "结果"}</b> `
        + `${escapeHtml(data.preview || "")}${data.ms ? ` · ${fmtMs(data.ms)}` : ""}</div>`
        + (data.output ? `<pre class="run-output">${escapeHtml(String(data.output).slice(0, 3000))}</pre>` : ""));
    } else if (item.kind === "confirm") {
      lines.push(`<div class="run-line"><b>确认</b> ${escapeHtml(data.summary || "")}</div>`);
    } else if (item.kind === "check") {
      const issues = Array.isArray(data.issues) ? data.issues : [];
      lines.push(`<div class="run-line ${data.ok ? "" : "bad"}"><b>自检</b> `
        + `${data.ok ? "通过" : escapeHtml(issues.join("；"))}</div>`);
    } else if (item.kind === "rewrite") {
      lines.push('<div class="run-line"><b>重写</b> 按自检结果替换了正文</div>');
    } else if (item.kind === "error") {
      lines.push(`<div class="run-line bad"><b>错误</b> ${escapeHtml(item.text || "")}</div>`);
    }
  }
  const counts = Object.entries(run.usage || {}).map(
    ([key, value]) => `${key}=${value}`).join(" · ");
  return `<div class="run-detail-body">${lines.join("") || '<div class="hint">没有可回放事件</div>'}
    <div class="hint">模型 ${escapeHtml(run.model || "—")} · 模型调用 ${run.model_calls} 次 · 工具 ${run.tool_count} 次
    ${counts ? ` · ${escapeHtml(counts)}` : ""}</div></div>`;
}
