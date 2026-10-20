// 页面共用的小工具：转义、时间、数字、提示条。没有框架，够用就好。

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** '2026-10-20 14:03:12' → '14:03' */
export function timeOf(stamp) {
  const text = String(stamp || "");
  return text.length >= 16 ? text.slice(11, 16) : text;
}

/** '2026-10-20 14:03:12' → '3 分钟前' / '14:03' */
export function relative(stamp) {
  const text = String(stamp || "");
  if (!text) return "";
  const then = new Date(text.replace(" ", "T"));
  if (Number.isNaN(then.getTime())) return timeOf(text);
  const seconds = Math.round((Date.now() - then.getTime()) / 1000);
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)} 天前`;
  return text.slice(0, 10);
}

export function todayLabel() {
  const now = new Date();
  const week = "日一二三四五六"[now.getDay()];
  return `${now.getFullYear()} 年 ${now.getMonth() + 1} 月 ${now.getDate()} 日 · 周${week}`;
}

/** 分钟 → {value, unit}：86 → 1 小时 26 分；0 → 0 分钟 */
export function minutesParts(minutes) {
  const total = Math.max(0, Math.round(Number(minutes) || 0));
  if (total < 60) return { value: String(total), unit: "分钟" };
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return { value: rest ? `${hours} 时 ${rest}` : String(hours), unit: rest ? "分" : "小时" };
}

export function charsParts(chars) {
  const total = Math.max(0, Number(chars) || 0);
  if (total < 10000) return { value: String(total), unit: "字" };
  return { value: (total / 10000).toFixed(1), unit: "万字" };
}

let toastTimer = 0;

export function toast(message, kind = "") {
  const node = document.getElementById("toast");
  if (!node) return;
  node.textContent = String(message || "");
  node.className = `toast ${kind}`.trim();
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 3200);
}

export function setStatus(text, kind = "") {
  const dot = document.getElementById("backend-dot");
  const label = document.getElementById("backend-text");
  if (dot) dot.className = `dot ${kind}`.trim();
  if (label) label.textContent = text;
}
