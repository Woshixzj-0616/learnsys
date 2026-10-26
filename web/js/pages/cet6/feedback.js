// 写作/翻译批改视图：档位、错误清单、二稿任务、参考范文（仅复盘）。
import { escapeHtml, relative } from "../../ui.js";
import { MODE_LABEL, splitSentences } from "./format.js";

const DIMENSIONS = {
  content: "内容切题", structure: "结构连贯", language: "语言准确",
  idiomatic: "表达地道", coverage: "信息点覆盖", accuracy: "准确性",
  fluency: "通顺度", terminology: "用词与术语",
};
const SEVERITY_CLASS = { "严重": "bad", "一般": "warn", "建议": "muted" };
const NON_CARD_TYPES = new Set(["结构", "审题"]);

function cardable(error) {
  return !NON_CARD_TYPES.has(error.type);
}

function dimensionChips(dimensions) {
  const rows = Object.entries(dimensions || {});
  if (!rows.length) return "";
  return `<div class="cet6-dims">${rows.map(([key, value]) => `
    <div class="cet6-dim">
      <span>${escapeHtml(DIMENSIONS[key] || key)}</span>
      <div class="cet6-dim-bar"><i style="width:${Math.round((Number(value) || 0) / 5 * 100)}%"></i></div>
      <b>${value == null ? "—" : escapeHtml(String(value))}/5</b>
    </div>`).join("")}</div>`;
}

function stabilityNote(review) {
  const stability = review?.stability;
  if (!stability || stability.stable !== false) return "";
  const bands = (stability.bands || []).join(" / ");
  return `<p class="cet6-warn">三次评分不稳定（${escapeHtml(bands)}），档位仅供参考；错误清单仍按原文逐条核对。</p>`;
}

function hardFlags(review) {
  const hard = review?.hard_rules || {};
  const flags = hard.flags || [];
  if (!flags.length && !review?.off_topic) return "";
  return `<section class="cet6-block">
    <h3>程序检查 <span class="hint">字数、分段、粘贴与离开页面</span></h3>
    <ul class="cet6-hard">
      ${review?.off_topic ? '<li class="bad">判定跑题，档位最高按 5 分档处理。</li>' : ""}
      ${flags.map((row) => `<li class="${SEVERITY_CLASS[row.level] || "muted"}">
        <b>${escapeHtml(row.level || "提示")}</b>：${escapeHtml(row.message || "")}</li>`).join("")}
    </ul>
  </section>`;
}

function infoPoints(review) {
  const points = review?.info_points;
  if (!points || points.total == null) return "";
  const missing = (points.missing_points || []).length
    ? `<p class="cet6-missing">漏译：${points.missing_points.map(escapeHtml).join("、")}</p>`
    : '<p class="cet6-missing ok">信息点没有明显漏译。</p>';
  return `<section class="cet6-block">
    <h3>信息点覆盖 <span class="hint">${points.covered ?? "—"} / ${points.total}</span></h3>
    ${missing}${points.notes ? `<p class="hint">${escapeHtml(points.notes)}</p>` : ""}
  </section>`;
}

function errorRows(errors) {
  if (!errors?.length) {
    return '<p class="hint">这次没有列出需要改的错误。</p>';
  }
  return `<div class="cet6-errors">${errors.map((error, index) => {
    const canCard = cardable(error);
    const auto = canCard && error.severity === "严重";
    const tail = auto
      ? '<span class="cet6-auto">已自动进错题本</span>'
      : (canCard
        ? `<button class="btn btn-small" type="button"
        data-act="add-card" data-index="${index}">加入错题本</button>`
        : '<span class="hint">结构/审题问题留在本次记录，不进复习队列</span>');
    return `<article class="cet6-error ${SEVERITY_CLASS[error.severity] || "muted"}">
      <div class="cet6-error-head">
        <span class="cet6-tag">${escapeHtml(error.type || "错误")}</span>
        <span class="cet6-sev ${SEVERITY_CLASS[error.severity] || "muted"}">${escapeHtml(error.severity || "一般")}</span>
        ${auto ? tail : ""}
      </div>
      <p class="cet6-quote">${escapeHtml(error.quote || "")}</p>
      <p class="cet6-fix">改为：${escapeHtml(error.fix || "—")}</p>
      ${error.why ? `<p class="hint">${escapeHtml(error.why)}</p>` : ""}
      ${auto ? "" : tail}
    </article>`;
  }).join("")}</div>`;
}

function translationComparison(detail) {
  if (detail.kind !== "translation" || !detail.segments?.length) return "";
  const mine = splitSentences(detail.text);
  const aligned = new Map(
    (detail.review?.alignment || []).map((row) => [Number(row.segment), row.quote]));
  const pointTable = detail.info_point_table || [];
  const rows = detail.segments.map((seg, index) => {
    const no = index + 1;
    const zh = seg.zh || "";
    const ref = seg.reference || "";
    const user = aligned.get(no) || mine[index] || "";
    const points = pointTable
      .filter((point) => (seg.info_points || []).includes(point.id))
      .map((point) => point.zh);
    return `<details class="cet6-compare-row">
      <summary><span>${escapeHtml(zh)}</span><span>${escapeHtml(user || "—")}</span><span>${escapeHtml(ref)}</span></summary>
      <p class="hint">信息点：${escapeHtml(points.join("、") || "无")}</p>
    </details>`;
  }).join("");
  const note = aligned.size
    ? ""
    : '<p class="hint">这次没有拿到逐句对齐，下面按原文顺序展示；你的整段译文见「我的原文」。</p>';
  return `<section class="cet6-block">
    <h3>逐句对照 <span class="hint">点一行看信息点</span></h3>
    ${note}
    <div class="cet6-compare">
      <div class="cet6-compare-head"><span>中文原句</span><span>我的译文</span><span>参考译文</span></div>
      ${rows}
    </div>
    ${detail.reference ? `<details class="cet6-compare-full"><summary>整段参考译文</summary>
      <p>${escapeHtml(detail.reference)}</p></details>` : ""}
  </section>`;
}

function translationTerms(detail) {
  if (!detail.terms?.length) return "";
  return `<section class="cet6-block">
    <h3>本篇术语 <span class="hint">点「加入生词本」按 FSRS 复习</span></h3>
    <div class="cet6-terms">
      ${detail.terms.map((term) => `<div class="cet6-term-row">
        <span class="cet6-term-zh">${escapeHtml(term.zh)}</span>
        <span class="cet6-term-en">${escapeHtml(term.en)}</span>
        ${term.note ? `<span class="hint">${escapeHtml(term.note)}</span>` : ""}
        <button class="btn btn-small" type="button" data-act="add-term"
          data-zh="${escapeHtml(term.zh)}" data-en="${escapeHtml(term.en)}"
          data-note="${escapeHtml(term.note || "")}">加入生词本</button>
      </div>`).join("")}
    </div>
  </section>`;
}

function modelEssay(detail) {
  const essay = detail.model_essay;
  if (!essay) return "";
  const paragraphs = String(essay.text || "").split(/\n\s*\n/).filter(Boolean);
  const notes = essay.notes || [];
  const noteFor = (index) => notes.find((row) => Number(row.paragraph) === index + 1)?.note || "";
  const upgrades = (detail.upgrades || []).map((row) => `
    <tr><td>${escapeHtml(row.low)}</td><td>${escapeHtml(row.high)}</td>
      <td>${escapeHtml(row.why)}</td></tr>`).join("");
  return `<details class="cet6-model">
    <summary>参考范文与升级对照（复盘用，不要在限时中看）</summary>
    <div class="cet6-model-body">
      ${paragraphs.map((text, index) => `<p>${escapeHtml(text)}</p>
        ${noteFor(index) ? `<p class="cet6-note">批注：${escapeHtml(noteFor(index))}</p>` : ""}`).join("")}
      ${upgrades ? `<table class="cet6-upgrades"><thead><tr><th>低分句</th><th>升级句</th><th>为什么</th></tr></thead>
        <tbody>${upgrades}</tbody></table>` : ""}
    </div>
  </details>`;
}

export function feedbackHtml(detail) {
  const review = detail.review || {};
  const band = detail.band;
  const cards = review.cards || [];
  const terms = review.term_cards || [];
  const score = detail.external_score;
  return `<div class="cet6-feedback">
    <header class="cet6-feedback-head">
      <div>
        <span class="cet6-kicker">${escapeHtml(detail.title || "写作")} · ${escapeHtml(MODE_LABEL[detail.mode] || detail.mode || "")} · ${escapeHtml(relative(detail.updated_at))}</span>
        <h2>批改结果</h2>
      </div>
      <div class="cet6-band">
        <strong>${band == null ? "—" : escapeHtml(String(band))}</strong>
        <span>${escapeHtml(review.band_label || "档位")}</span>
      </div>
    </header>

    ${stabilityNote(review)}
    <p class="cet6-band-reason">${escapeHtml(review.band_reason || "")}</p>
    ${dimensionChips(review.dimensions)}

    <div class="cet6-feedback-grid">
      <section class="cet6-block">
        <h3>先改这 3 处</h3>
        <ol class="cet6-priorities">${(review.priorities || []).map(
          (row) => `<li>${escapeHtml(row)}</li>`).join("") || '<li class="hint">没有给出优先级。</li>'}</ol>
        <p class="cet6-rewrite">${escapeHtml(review.rewrite_task || "")}</p>
      </section>
      <section class="cet6-block">
        <h3>这次收进复习</h3>
        <p>严重错误自动进错题本：<b>${cards.length}</b> 条${terms.length ? `；术语卡：<b>${terms.length}</b> 条` : ""}。</p>
        <p class="hint">一般错误可以逐条点「加入错题本」。错题会按 FSRS 排期出现，不会重复收同一条。</p>
        <div class="cet6-actions">
          <a class="btn btn-small" href="#/wrongbook" data-act="go-wrongbook">打开错题本</a>
          <button class="btn btn-small" type="button" data-act="rewrite" data-id="${detail.id}">写二稿</button>
          <button class="btn btn-small" type="button" data-act="review-again" data-id="${detail.id}">重新批改</button>
        </div>
      </section>
    </div>

    ${hardFlags(review)}
    ${infoPoints(review)}

    <section class="cet6-block">
      <h3>错误清单</h3>
      ${errorRows(review.errors)}
    </section>

    <section class="cet6-block cet6-external">
      <h3>外部校准分 <span class="hint">老师或真题分数，按 0–15 档录</span></h3>
      <div class="cet6-inline-form">
        <input id="cet6-score-input" type="number" min="0" max="15" step="0.5"
          value="${score == null ? "" : escapeHtml(String(score))}" placeholder="例如 10.5">
        <button class="btn btn-small" type="button" data-act="score" data-id="${detail.id}">保存分数</button>
        ${score == null ? "" : `<span class="hint">当前：${escapeHtml(String(score))} 分</span>`}
      </div>
    </section>

    <section class="cet6-block">
      <h3>我的原文 <span class="hint">${detail.word_count} 词 · ${Math.round((detail.duration_s || 0) / 60)} 分钟</span></h3>
      <p class="cet6-original">${escapeHtml(detail.text || "")}</p>
      ${detail.parent ? `<p class="hint">初稿档位 ${detail.parent.band == null ? "—" : detail.parent.band}，二稿档位 ${band == null ? "—" : band}。</p>` : ""}
    </section>

    ${translationComparison(detail)}
    ${translationTerms(detail)}
    ${modelEssay(detail)}
    <div class="cet6-actions">
      <button class="btn" type="button" data-act="back">返回</button>
    </div>
  </div>`;
}
