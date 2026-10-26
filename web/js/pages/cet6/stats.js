// 统计页：档位趋势、错误画像、训练量（只读；数据来自 /api/cet6/train/stats）。
import { api } from "../../api.js";
import { escapeHtml } from "../../ui.js";
import {
  bandText, formatMinutes, overallBand, trendBar,
} from "./stats-format.js";

let panel = null;
let ctx = null;

function statRow(label, value, note = "") {
  return `<div class="cet6-stat"><span>${escapeHtml(label)}</span>
    <strong>${escapeHtml(value)}${note ? `<small>${escapeHtml(note)}</small>` : ""}</strong></div>`;
}

function kindCard(kind, row) {
  const label = kind === "writing" ? "写作" : "翻译";
  const rows = [
    statRow("完成", String(row.submissions || 0), " 篇"),
    statRow("平均档位", bandText(row.avg_band)),
    statRow("最近档位", bandText(row.last_band)),
    statRow("严重错误", String(row.serious || 0), " 处"),
    statRow("严重错误/百词", String(row.serious_per_100_words ?? 0)),
  ];
  if (kind === "translation") {
    rows.splice(1, 0, statRow("一句一译", String(row.sentences || 0), " 次"));
    rows.push(statRow("信息点覆盖", row.info_rate == null ? "—" : `${row.info_rate}%`));
  }
  rows.push(statRow("训练时长", formatMinutes(row.minutes || 0)));
  return `<section class="cet6-stat-card">
    <div class="cet6-section-head"><h3>${label}</h3></div>
    ${rows.join("")}
  </section>`;
}

function trendHtml(rows) {
  if (!rows?.length) {
    return '<p class="hint">还没有批改记录。完成一篇写作或整段翻译后，这里会出现档位趋势。</p>';
  }
  const head = `<div class="cet6-trend-row cet6-trend-head">
    <span>日期</span><span>写作</span><span>翻译</span></div>`;
  const body = rows.map((row) => {
    const writing = trendBar(row.writing);
    const translation = trendBar(row.translation);
    return `<div class="cet6-trend-row">
      <span class="cet6-trend-date">${escapeHtml((row.date || "").slice(5))}</span>
      <span class="cet6-trend-cell"><span class="cet6-trend-bar ${writing.level}">
        <i style="width:${writing.width}%"></i></span><b>${writing.text}</b></span>
      <span class="cet6-trend-cell"><span class="cet6-trend-bar ${translation.level}">
        <i style="width:${translation.width}%"></i></span><b>${translation.text}</b></span>
    </div>`;
  }).join("");
  return `<div class="cet6-trend">${head}${body}</div>`;
}

function errorHtml(rows) {
  if (!rows?.length) return '<p class="hint">还没有错误记录。</p>';
  const top = Math.max(...rows.map((row) => Number(row.count) || 0), 1);
  return rows.map((row) => `<div class="cet6-error-row">
    <span class="cet6-error-name">${escapeHtml(row.type || "未分类")}</span>
    <span class="cet6-error-bar"><i style="width:${Math.round((Number(row.count) || 0) * 100 / top)}%"></i></span>
    <span class="cet6-error-count">${escapeHtml(String(row.count || 0))}
      ${row.serious ? `<em>严重 ${escapeHtml(String(row.serious))}</em>` : ""}</span>
  </div>`).join("");
}

async function render() {
  panel.innerHTML = '<div class="empty">正在统计训练数据…</div>';
  try {
    const [stats, plan] = await Promise.all([
      api.get("/api/cet6/train/stats?days=30"),
      api.get("/api/cet6/train/plan"),
    ]);
    const totals = stats.totals || {};
    const byKind = stats.by_kind || {};
    const average = overallBand(byKind);
    const count = (Number(totals.submissions) || 0) + (Number(totals.sentences) || 0);
    const due = plan.due || {};
    const info = stats.info_points || {};

    panel.innerHTML = `
      <div class="cet6-hero">
        <div class="cet6-hero-main">
          <span class="cet6-kicker">近 ${stats.range?.days || 30} 天六级训练</span>
          <h2>${count ? `平均 ${bandText(average)} 档 · 共 ${count} 次训练` : "还没有训练记录"}</h2>
          <p class="hint">写作 ${byKind.writing?.submissions || 0} 篇 ·
            整段翻译 ${byKind.translation?.submissions || 0} 篇 ·
            一句一译 ${totals.sentences || 0} 次 · ${formatMinutes(totals.minutes || 0)}</p>
          <div class="cet6-actions">
            <a class="btn btn-primary" href="#/cet6?tab=writing">去写作</a>
            <a class="btn" href="#/cet6?tab=translation">去翻译</a>
            ${due.total ? `<a class="btn btn-small" href="#/cet6?tab=review">${due.total} 张到期错卡</a>`
              : '<a class="btn btn-small" href="#/wrongbook">错题本</a>'}
          </div>
        </div>
        <div class="cet6-hero-side">
          ${statRow("连续训练", String(plan.streak || 0), " 天")}
          ${statRow("严重错误", String(totals.serious || 0), " 处")}
          ${statRow("到期错卡", String(due.total || 0), " 张")}
        </div>
      </div>

      <div class="cet6-section-head"><h3>档位趋势</h3>
        <span class="hint">每天取平均档位；柱长 = 0–15 档</span></div>
      ${trendHtml(stats.band_trend || [])}

      <div class="cet6-stats-grid">
        ${kindCard("writing", byKind.writing || {})}
        ${kindCard("translation", byKind.translation || {})}
        <section class="cet6-stat-card">
          <div class="cet6-section-head"><h3>错误画像</h3></div>
          ${errorHtml(stats.error_types || [])}
        </section>
        <section class="cet6-stat-card">
          <div class="cet6-section-head"><h3>信息点覆盖</h3></div>
          ${statRow("覆盖", info.rate == null ? "—" : `${info.rate}%`)}
          ${statRow("已覆盖", String(info.covered || 0), " 个")}
          ${statRow("应覆盖", String(info.total || 0), " 个")}
          <p class="hint">只统计整段翻译；一句一译不计入信息点。</p>
        </section>
      </div>`;
    ctx.setSub(count ? `统计 · 近 30 天 ${count} 次训练` : "统计 · 还没有训练记录");
  } catch (error) {
    panel.innerHTML = `<div class="empty"><strong>统计没加载出来</strong>
      ${escapeHtml(error.message || "")}</div>`;
  }
}

export async function mount(context) {
  panel = context.panel;
  ctx = context.ctx;
  await render();
}
