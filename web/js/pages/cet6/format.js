// 写作页共用的小格式：词数、倒计时、模式/状态标签（纯函数，前端测试直接跑）。
const WORDS = /[A-Za-z][A-Za-z'’-]*/g;

export const MODE_LABEL = { timed: "限时", practice: "练习", rewrite: "二稿" };
export const STATUS_LABEL = {
  draft: "草稿", reviewing: "批改中", reviewed: "已批改", failed: "失败",
};

export function statusLabel(status) {
  return STATUS_LABEL[status] || status || "未知";
}

export function countWords(text) {
  return (String(text || "").match(WORDS) || []).length;
}

export function cjkCount(text) {
  return (String(text || "").match(/[一-鿿]/g) || []).length;
}

export function splitSentences(text) {
  return String(text || "").replace(/\s+/g, " ").trim()
    .split(/(?<=[.!?])\s+/).filter(Boolean);
}

export function clock(seconds) {
  const left = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = String(Math.floor(left / 60)).padStart(2, "0");
  const s = String(left % 60).padStart(2, "0");
  return `${m}:${s}`;
}

// 编辑器初始文本：二稿 > 已存草稿 > 首句续写预填 > 空。
export function initialEditorText({ initialText, submissionText, mode, leadSentence }) {
  if (initialText) return initialText;
  if (String(submissionText || "").trim()) return submissionText;
  if (mode === "rewrite") return "";
  const lead = String(leadSentence || "").trim();
  return lead ? `${lead}\n\n` : "";
}

// 题库本地筛选：field 为空表示「全部」，未知筛选值回退到全部。
export function filterByField(items, field, value) {
  const rows = Array.isArray(items) ? items : [];
  if (!value) return rows;
  return rows.filter((item) => item?.[field] === value);
}
