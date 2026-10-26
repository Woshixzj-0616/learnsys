// 翻译页的纯视图模板：只拼 HTML，不碰状态与网络。
import { escapeHtml, relative } from "../../ui.js";
import { MODE_LABEL, cjkCount, statusLabel } from "./format.js";

function subnav(active) {
  const tabs = [
    ["home", "今日"], ["sentence", "一句一译"], ["library", "题库"],
    ["terms", "术语"], ["history", "历史"],
  ];
  return `<div class="cet6-subnav">${tabs.map(([key, label]) =>
    `<button class="cet6-subtab${active === key ? " active" : ""}" type="button"
      data-act="view" data-view="${key}">${label}</button>`).join("")}</div>`;
}

function historyRow(item) {
  return `<button class="cet6-history-row" type="button" data-act="open-sub" data-id="${item.id}">
    <span class="cet6-history-title">${escapeHtml(item.title || item.prompt_id)}</span>
    <span class="cet6-history-meta">${escapeHtml(MODE_LABEL[item.mode] || item.mode || "")} ·
      ${escapeHtml(statusLabel(item.status))} · ${escapeHtml(relative(item.updated_at))}</span>
    <span class="cet6-history-band${item.status === "reviewed" ? "" : " muted"}">${escapeHtml(String(item.band ?? "—"))}</span>
  </button>`;
}

export function homeHtml({ prompts, todayPrompt, todaySentence, recent, last,
                           attemptedCount }) {
  const done = prompts.filter((row) => row.done > 0).length;
  return `${subnav("home")}
    <div class="cet6-hero">
      <div class="cet6-hero-main">
        <span class="cet6-kicker">每日翻译 · 一句一译</span>
        <h2>${escapeHtml(todaySentence?.zh || "题库还没加载出来")}</h2>
        <p class="hint">${escapeHtml(todaySentence?.skill || "")} · 提交后立即审核，再译一遍固化。</p>
        <div class="cet6-actions">
          <button class="btn btn-primary" type="button" data-act="view" data-view="sentence">开始一句一译</button>
          <button class="btn" type="button" data-act="start-whole"
            data-id="${escapeHtml(todayPrompt?.id || "t01")}" data-mode="timed">整段限时</button>
          <button class="btn btn-small" type="button" data-act="view" data-view="terms">术语卡</button>
        </div>
      </div>
      <div class="cet6-hero-side">
        <div class="cet6-stat"><span>整篇已练</span><strong>${done}/${prompts.length}</strong></div>
        <div class="cet6-stat"><span>单句已练</span><strong>${attemptedCount || 0}</strong></div>
        <div class="cet6-stat"><span>最近档位</span><strong>${last?.band == null ? "—" : last.band}</strong></div>
        <div class="cet6-stat"><span>到期错误卡</span><a href="#/cet6?tab=review">去复习</a></div>
      </div>
    </div>
    <div class="cet6-section-head"><h3>最近的整篇练习</h3>
      <button class="btn btn-small" type="button" data-act="view" data-view="history">全部历史</button></div>
    ${recent.length ? `<div class="cet6-history">${recent.map(historyRow).join("")}</div>`
      : '<p class="hint">还没有整篇翻译记录；先用「一句一译」练熟。</p>'}`;
}

export function sentenceHintsHtml(sentence, hintLevel) {
  if (!sentence || hintLevel < 1) return "";
  const keywords = (sentence.keywords || []).map(
    (word) => `<span class="cet6-chip">${escapeHtml(word)}</span>`).join("");
  const skeleton = hintLevel >= 2
    ? `<p class="cet6-skeleton"><b>句子骨架：</b>${escapeHtml(sentence.skeleton || "")}</p>`
    : "";
  return `<div class="cet6-sentence-hints">
    <div><b>提示 1 · 关键词：</b>${keywords || "（没有关键词）"}</div>
    ${skeleton}
  </div>`;
}

export function sentenceResultHtml(data) {
  const review = data.review;
  const classOf = {
    "准确": "ok", "基本准确": "ok", "有偏差": "warn", "误译": "bad",
  }[review.conclusion] || "warn";
  const points = review.info_points || {};
  const must = review.must_fix || [];
  const suggestions = review.suggestions || [];
  return `<section class="cet6-sentence-result">
    <div class="cet6-sentence-head">
      <span class="cet6-sentence-conclusion ${classOf}">${escapeHtml(review.conclusion || "有偏差")}</span>
      <span class="hint">信息点 ${points.covered ?? "—"} / ${points.total ?? "—"} · 用时 ${((data.ms || 0) / 1000).toFixed(1)} 秒</span>
    </div>
    ${(points.missing || []).length
      ? `<p class="cet6-missing">漏了：${points.missing.map(escapeHtml).join("、")}</p>` : ""}
    ${must.length ? `<div class="cet6-sentence-list">
      <h4>必改 ${data.cards_added ? `（已自动进错题本 ${data.cards_added} 条）` : ""}</h4>
      ${must.map((row) => `<div class="cet6-sentence-error">
        <p class="cet6-quote">${escapeHtml(row.quote)}</p>
        <p class="cet6-fix">改为：${escapeHtml(row.fix)}</p>
        ${row.why ? `<p class="hint">${escapeHtml(row.why)}</p>` : ""}
      </div>`).join("")}</div>` : '<p class="hint">没有必改项。</p>'}
    ${suggestions.length ? `<div class="cet6-sentence-list">
      <h4>建议（只展示，不进错题本）</h4>
      ${suggestions.map((row) => `<div class="cet6-sentence-error">
        <p class="cet6-quote">${escapeHtml(row.quote || "")}</p>
        <p class="cet6-fix">可以改成：${escapeHtml(row.fix)}</p>
        ${row.why ? `<p class="hint">${escapeHtml(row.why)}</p>` : ""}
      </div>`).join("")}</div>` : ""}
    <div class="cet6-sentence-versions">
      <div><span>参考译文</span><p>${escapeHtml(review.reference || "")}</p></div>
      ${(review.variants || []).length ? `<div><span>也可接受</span><p>${review.variants.map(escapeHtml).join("<br>")}</p></div>` : ""}
      ${review.minimal_fix ? `<div><span>最小改动版</span><p>${escapeHtml(review.minimal_fix)}</p></div>` : ""}
      ${review.idiomatic ? `<div><span>更地道版</span><p>${escapeHtml(review.idiomatic)}</p></div>` : ""}
    </div>
    <div class="cet6-actions">
      <button class="btn btn-primary" type="button" data-act="sentence-retry">再译一遍</button>
      <button class="btn" type="button" data-act="sentence-next-skill">换同技能新句</button>
      <button class="btn btn-small" type="button" data-act="sentence-next">下一句</button>
    </div>
  </section>`;
}

export function sentenceViewHtml({ sentence, skills, skill, attemptedCount,
                                  hintLevel, resultHtml }) {
  const options = ['<option value="">全部技能</option>'].concat(
    skills.map((name) => `<option value="${escapeHtml(name)}"${name === skill ? " selected" : ""}>${escapeHtml(name)}</option>`)).join("");
  return `${subnav("sentence")}
    <div class="cet6-sentence-toolbar">
      <label class="hint">技能 <select id="cet6-skill">${options}</select></label>
      <span class="hint">已练 ${attemptedCount || 0} 句 · 提交前不显示参考译文</span>
    </div>
    <article class="cet6-sentence-card">
      <span class="cet6-kicker">${escapeHtml(sentence.skill || "")}${sentence.source_title ? ` · ${escapeHtml(sentence.source_title)}` : ""}</span>
      <p class="cet6-source-zh">${escapeHtml(sentence.zh)}</p>
      ${sentenceHintsHtml(sentence, hintLevel)}
      <textarea id="cet6-sentence-text" spellcheck="false" placeholder="写下你的英文译文…"></textarea>
      <div class="cet6-write-foot">
        <div class="cet6-actions">
          <button class="btn btn-small" type="button" data-act="sentence-hint-1">卡住了 · 关键词</button>
          <button class="btn btn-small" type="button" data-act="sentence-hint-2"${hintLevel < 1 ? " disabled" : ""}>提示 2 · 句子骨架</button>
          <button class="btn btn-small" type="button" data-act="sentence-next">换一句</button>
        </div>
        <button class="btn btn-primary" type="button" data-act="sentence-submit">提交审核</button>
      </div>
      <div id="cet6-sentence-result">${resultHtml || ""}</div>
    </article>`;
}

export function libraryHtml(prompts) {
  return `${subnav("library")}
    <div class="cet6-grid">${prompts.map((item) => {
      const meta = item.done
        ? `已练 ${item.done} 次 · 最近 ${item.last_band == null ? "—" : item.last_band} 档`
        : "还没练过";
      return `<button class="cet6-card" type="button" data-act="open-prompt" data-id="${escapeHtml(item.id)}">
        <span class="cet6-card-kicker">${escapeHtml(item.theme || "")} · 难度 ${item.difficulty || 1}</span>
        <strong>${escapeHtml(item.title)}</strong>
        <span class="cet6-card-meta">${escapeHtml(meta)}</span>
      </button>`;
    }).join("")}</div>
    <p class="hint">整段限时只给中文原文；提交后给档位、错误清单、逐句对照和参考译文。</p>`;
}

export function promptViewHtml(prompt) {
  return `${subnav("library")}
    <article class="cet6-prompt-detail">
      <span class="cet6-kicker">${escapeHtml(prompt.theme || "")} · 难度 ${prompt.difficulty || 1} ·
        ${prompt.minutes || 30} 分钟 · 原文 ${cjkCount(prompt.source_zh)} 字</span>
      <h2>${escapeHtml(prompt.title)}</h2>
      <p class="cet6-source-zh">${escapeHtml(prompt.source_zh || "")}</p>
      <div class="cet6-actions">
        <button class="btn btn-primary" type="button" data-act="start-whole"
          data-id="${escapeHtml(prompt.id)}" data-mode="timed">开始整段限时</button>
        <button class="btn" type="button" data-act="start-whole"
          data-id="${escapeHtml(prompt.id)}" data-mode="practice">练习模式</button>
        <button class="btn btn-small" type="button" data-act="view" data-view="library">返回题库</button>
      </div>
    </article>`;
}

export function termsHtml(terms) {
  return `${subnav("terms")}
    <div class="cet6-sentence-toolbar">
      <input id="cet6-term-search" type="search" placeholder="搜中文或英文…">
      <span class="hint">共 ${terms.length} 张；加入生词本后按 FSRS 到期复习</span>
    </div>
    <div class="cet6-terms" id="cet6-term-list">${terms.map(termRow).join("")}</div>`;
}

function termRow(term) {
  return `<div class="cet6-term-row" data-search="${escapeHtml((term.zh + " " + term.en).toLowerCase())}">
    <span class="cet6-term-zh">${escapeHtml(term.zh)}</span>
    <span class="cet6-term-en">${escapeHtml(term.en)}</span>
    ${term.note ? `<span class="hint">${escapeHtml(term.note)}</span>` : "<span></span>"}
    <button class="btn btn-small" type="button" data-act="add-term"
      data-zh="${escapeHtml(term.zh)}" data-en="${escapeHtml(term.en)}"
      data-note="${escapeHtml(term.note || "")}">加入生词本</button>
  </div>`;
}

export function historyHtml(rows) {
  return `${subnav("history")}
    ${rows.length ? `<div class="cet6-history">${rows.map(historyRow).join("")}</div>`
      : '<p class="hint">还没有整篇翻译提交；单句练习在「一句一译」里。</p>'}`;
}

export function progressHtml(id) {
  return `<div class="cet6-progress">
    <div class="cet6-progress-mark">···</div>
    <h2>正在批改整段翻译</h2>
    <p>三次评分取中位，通常 10 秒左右；关掉页面也会继续。</p>
    <p class="hint">已等待 0 秒</p>
    <div class="cet6-actions">
      <button class="btn btn-small" type="button" data-act="open-sub" data-id="${id}">刷新一下</button>
      <button class="btn btn-small" type="button" data-act="view" data-view="history">先看历史</button>
    </div></div>`;
}

export function failedHtml(detail) {
  return `<div class="cet6-progress">
    <h2>批改没有完成</h2>
    <p class="cet6-warn">${escapeHtml(detail.error || "模型没有返回可用结果")}</p>
    <div class="cet6-actions">
      <button class="btn btn-primary" type="button" data-act="review-again" data-id="${detail.id}">重新批改</button>
      <button class="btn" type="button" data-act="edit" data-id="${detail.id}">改正文</button>
      <button class="btn btn-small" type="button" data-act="view" data-view="history">回历史</button>
    </div></div>`;
}
