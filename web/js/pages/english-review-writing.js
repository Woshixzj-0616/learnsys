// 写作句型卡的三关模板：只拼 HTML，不碰 DOM，方便 node --test 直接测。
// 第 1 关只给中文例句，第 2 关只给中文用途，第 3 关给用途 + 换主题；
// 背面（reveal 后）才出现英文句型、参考例句和关键词对照。
import { escapeHtml } from "../ui.js";
import { keywordCoverage, patternHint, patternSlots } from "./english-review-round.js";

const STAGE_LABELS = ["例句回译", "句型默写", "换主题造句"];
const STAGE_MARKS = ["①", "②", "③"];
const STAGE_NOTES = {
  1: "下一关：复习 2 次且记牢后，改成默写句型",
  2: "下一关：再记牢一些，改成换主题造句",
  3: "最后一关：把句型用到新主题",
};

function stepsHtml(stage) {
  return `<ol class="er-steps" aria-label="写作句型复习进度">${
    STAGE_LABELS.map((name, index) => {
      const number = index + 1;
      const state = number === stage ? "current"
        : number < stage ? "done" : "";
      const current = number === stage ? ' aria-current="step"' : "";
      return `<li class="${state}"${current}>${STAGE_MARKS[index]} ${escapeHtml(name)}</li>`;
    }).join("")
  }</ol>`;
}

function noteHtml(stage) {
  const note = STAGE_NOTES[stage];
  return note ? `<p class="er-stage-note">${escapeHtml(note)}</p>` : "";
}

function inputHtml(placeholder, typed) {
  return `<textarea class="er-typed" id="er-typed" autocomplete="off"
    autocapitalize="off" spellcheck="false"
    placeholder="${escapeHtml(placeholder)}">${escapeHtml(typed)}</textarea>`;
}

function typedBlockHtml(label, typed) {
  return `<div class="er-block">
    <div class="er-label">${escapeHtml(label)}</div>
    <pre class="er-mine">${escapeHtml(typed)}</pre></div>`;
}

function coverageHtml(result, label) {
  if (!result.total) return "";
  const shown = result.missing.slice(0, 8);
  const rest = result.missing.length - shown.length;
  const missing = shown.map(escapeHtml).join("、") + (rest > 0 ? ` 等 ${rest} 个` : "");
  const tail = result.missing.length
    ? `<span class="er-coverage-rest">参考里还有：${missing}</span>`
    : '<span class="er-coverage-ok">参考里的关键词都覆盖到了</span>';
  return `<div class="er-coverage">
    <span class="er-coverage-head">${escapeHtml(label)} ${result.hit}/${result.total}</span>
    ${tail}</div>`;
}

function hintHtml(pattern, hintUsed) {
  if (!patternSlots(pattern)) return "";
  if (!hintUsed) {
    return `<button class="btn btn-small er-hint-toggle" type="button"
      id="er-hint">先给个提示</button>`;
  }
  return `<div class="er-hint-box">
    <span class="er-hint-label">句型骨架（只给固定词）</span>
    <code>${escapeHtml(patternHint(pattern))}</code>
  </div>`;
}

function frontHtml(stage, card, view, exampleZh, pattern, use, topic) {
  if (stage === 1) {
    return `
      <div class="er-label">中文例句</div>
      <div class="er-prompt">${escapeHtml(exampleZh || "（这条没有例句译文）")}</div>
      ${use ? `<div class="er-usecase">这次要练：${escapeHtml(use)}</div>` : ""}
      ${view.revealed ? "" : hintHtml(pattern, view.hintUsed)}
      ${view.revealed ? "" : inputHtml("先自己译一遍；尽量用上这个句型", view.typed)}`;
  }
  if (stage === 2) {
    const slots = patternSlots(pattern);
    return `
      <div class="er-label">中文用途</div>
      <div class="er-prompt">${escapeHtml(use || "（这条没有用途说明）")}</div>
      ${slots ? `<div class="er-usecase">这个句型有 ${slots} 个空位。</div>` : ""}
      ${view.revealed ? "" : inputHtml("默写英文句型；空缺处用 ... 或 ____ 表示", view.typed)}`;
  }
  const topicLine = topic
    ? `换主题：以「${escapeHtml(topic)}」为题，用这个句型写一句英文。`
    : "换一个和参考例句不同的主题，用这个句型写一句英文。";
  return `
    <div class="er-label">中文用途</div>
    <div class="er-prompt">${escapeHtml(use || "（这条没有用途说明）")}</div>
    <div class="er-topic">${topicLine}</div>
    ${view.revealed ? "" : inputHtml("写一句完整的英文；句型要和参考一致", view.typed)}`;
}

function backHtml(stage, card, view, example, exampleZh, pattern, ratingsHtml) {
  const exampleText = example || "（这条没有参考例句）";
  const exampleBlock = `
    <div class="er-block">
      <div class="er-label">${stage === 3 ? "原参考例句" : "参考例句"}</div>
      <div class="er-example">${escapeHtml(exampleText)}</div>
      ${exampleZh ? `<div class="er-example-zh">${escapeHtml(exampleZh)}</div>` : ""}
    </div>`;
  const patternBlock = `
    <div class="er-block">
      <div class="er-label">参考句型</div>
      <div class="er-pattern">${escapeHtml(pattern)}</div>
    </div>`;
  const hintNote = view.hintUsed
    ? '<div class="er-note">这次看了句型骨架；评分按真实回忆程度选。</div>' : "";
  const note = card.note
    ? `<div class="er-note">${escapeHtml(card.note)}</div>` : "";

  if (stage === 1) {
    return `
      ${exampleBlock}
      ${patternBlock}
      ${coverageHtml(keywordCoverage(example, view.typed), "关键词对照")}
      ${view.typed ? typedBlockHtml("我的译文", view.typed) : ""}
      ${hintNote}
      ${note}
      ${ratingsHtml}`;
  }
  if (stage === 2) {
    return `
      ${patternBlock}
      ${exampleBlock}
      ${coverageHtml(keywordCoverage(pattern, view.typed), "句型固定词")}
      ${view.typed ? typedBlockHtml("我的默写", view.typed) : ""}
      ${note}
      ${ratingsHtml}`;
  }
  return `
    ${patternBlock}
    ${exampleBlock}
    ${coverageHtml(keywordCoverage(pattern, view.typed), "句型固定词")}
    ${view.typed ? typedBlockHtml("我写的句子", view.typed) : ""}
    <div class="er-selfcheck">自查：句型固定词都用上了吗？句子回应主题了吗？
      主语、谓语和时态完整吗？能直接放进作文吗？</div>
    ${note}
    ${ratingsHtml}`;
}

export function writingCardHtml(card, view, { metaHtml = "", ratingsHtml = "" } = {}) {
  const stage = Number(view?.stage || 0);
  if (!stage) {
    return `<div class="er-card">${metaHtml}
      <div class="empty">这条写作句型缺内容，先按真实情况自评跳过。</div>
      ${ratingsHtml}</div>`;
  }
  const pattern = String(card?.pattern || card?.answer || "").trim();
  const example = String(card?.example || "").trim();
  const exampleZh = String(card?.example_zh || "").trim();
  const use = String(card?.question || "").trim();
  const topic = String(card?.topic || "").trim();
  const front = frontHtml(stage, card, view, exampleZh, pattern, use, topic);
  const back = view.revealed
    ? backHtml(stage, card, view, example, exampleZh, pattern, ratingsHtml)
    : "";
  const showText = view.revealed
    ? "收起，再试一次"
    : (stage === 1 ? "看参考例句" : "看参考句型");
  return `
    <div class="er-card">
      ${metaHtml}
      ${stepsHtml(stage)}
      ${noteHtml(stage)}
      ${front}
      <div class="er-reveal"><button class="btn btn-primary" type="button" id="er-show">
        ${showText}</button></div>
      <div class="er-answer" ${view.revealed ? "" : "hidden"}>${back}</div>
    </div>`;
}
