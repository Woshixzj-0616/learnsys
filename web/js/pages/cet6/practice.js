// 专项页外壳：在「逐句听写」和「真题自评」之间切换，共用同一块面板。
import { escapeHtml } from "../../ui.js";

const MODES = { drill: "逐句听写", exam: "真题自评", chunk: "意群长句" };

let host = null;
let ctx = null;
let mode = "drill";
let cleanup = null;
let token = 0;

function barHtml() {
  const buttons = Object.entries(MODES).map(([key, label]) =>
    `<button class="cet6-mode ${key === mode ? "active" : ""}" type="button"
      data-mode="${key}" role="tab" aria-selected="${key === mode}">
      ${escapeHtml(label)}</button>`).join("");
  return `<div class="cet6-modebar" role="tablist" aria-label="专项模式">
      ${buttons}
    </div>
    <div class="cet6-practice-body" id="cet6-practice-body"></div>`;
}

function markMode(next) {
  for (const button of host?.querySelectorAll("[data-mode]") || []) {
    const on = button.dataset.mode === next;
    button.classList.toggle("active", on);
    button.setAttribute("aria-selected", on ? "true" : "false");
  }
}

function rememberMode(next) {
  try {
    const raw = location.hash.replace(/^#\/?/, "");
    const [, queryPart] = raw.split("?");
    const params = new URLSearchParams(queryPart || "");
    params.set("tab", "drill");
    params.set("mode", next);
    history.replaceState(null, "", `#/cet6?${params.toString()}`);
  } catch {
    // 地址栏改不了不影响切换
  }
}

async function mountMode(next) {
  token += 1;
  const mine = token;
  if (cleanup) {
    try { cleanup(); } catch { /* 页面自己收尾失败不影响切换 */ }
    cleanup = null;
  }
  mode = next;
  const body = host?.querySelector("#cet6-practice-body");
  if (!body) return;
  body.innerHTML = "";
  if (next === "exam") {
    const page = await import("./exam.js");
    if (mine !== token) return;
    cleanup = await page.mount({ panel: body, ctx });
    return;
  }
  if (next === "chunk") {
    const page = await import("./chunk.js");
    if (mine !== token) return;
    cleanup = await page.mount({ panel: body, ctx });
    return;
  }
  const page = await import("./drill.js");
  if (mine !== token) return;
  cleanup = await page.mount({ panel: body, ctx });
}

function onClick(event) {
  const button = event.target.closest("[data-mode]");
  if (!button || !host?.contains(button)) return;
  const next = button.dataset.mode;
  if (!MODES[next] || next === mode) return;
  event.preventDefault();
  markMode(next);
  rememberMode(next);
  mountMode(next);
}

function modeFromHash() {
  try {
    const raw = location.hash.replace(/^#\/?/, "");
    const [, queryPart] = raw.split("?");
    return new URLSearchParams(queryPart || "").get("mode") || "";
  } catch {
    return "";
  }
}

export async function mount(context) {
  host = context.panel;
  ctx = context.ctx;
  const requested = modeFromHash() || ctx.query?.get("mode");
  mode = MODES[requested] ? requested : "drill";
  host.innerHTML = barHtml();
  host.addEventListener("click", onClick);
  await mountMode(mode);
  return () => {
    token += 1;
    host?.removeEventListener("click", onClick);
    if (cleanup) {
      try { cleanup(); } catch { /* 忽略 */ }
      cleanup = null;
    }
    host = null;
    ctx = null;
  };
}
