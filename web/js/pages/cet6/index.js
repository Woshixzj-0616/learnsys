// 六级训练壳：精听 iframe 保原样，写作/翻译/统计是原生页。
import { mountListening } from "./listening.js";

const TABS = {
  listening: "精听",
  writing: "写作",
  translation: "翻译",
  stats: "统计",
};
const SUBTITLES = {
  listening: "原精听工作台：试卷、断点、回听与分析",
  writing: "题库、限时写作、批改与二稿",
  translation: "一句一译、整段限时、术语卡与逐句对照",
  stats: "档位趋势、错误画像与训练量",
};

let root = null;
let panel = null;
let cleanup = null;
let active = "";

function markTabs(tab) {
  for (const button of root?.querySelectorAll(".cet6-tab") || []) {
    const on = button.dataset.tab === tab;
    button.classList.toggle("active", on);
    button.setAttribute("aria-selected", on ? "true" : "false");
  }
}

function rememberTab(tab) {
  try {
    const raw = location.hash.replace(/^#\/?/, "");
    const [, queryPart] = raw.split("?");
    const params = new URLSearchParams(queryPart || "");
    params.set("tab", tab);
    history.replaceState(null, "", `#/cet6?${params.toString()}`);
  } catch {
    // 地址栏改不了不影响页面
  }
}

async function switchTab(tab, ctx) {
  if (!TABS[tab]) tab = "listening";
  if (tab === active && cleanup) return;
  if (cleanup) {
    try { cleanup(); } catch { /* 页面自己收尾失败不影响换标签 */ }
    cleanup = null;
  }
  active = tab;
  markTabs(tab);
  rememberTab(tab);
  ctx.setSub(SUBTITLES[tab]);
  ctx.setActions("");
  panel.innerHTML = "";

  if (tab === "listening") {
    cleanup = mountListening(panel, ctx.query);
    return;
  }
  if (tab === "writing") {
    const page = await import("./writing.js");
    if (active !== "writing") return;
    cleanup = await page.mount({ panel, ctx });
    return;
  }
  if (tab === "translation") {
    const page = await import("./translation.js");
    if (active !== "translation") return;
    cleanup = await page.mount({ panel, ctx });
    return;
  }
  if (tab === "stats") {
    const page = await import("./stats.js");
    if (active !== "stats") return;
    cleanup = await page.mount({ panel, ctx });
    return;
  }
}

export async function mount(ctx) {
  root = ctx.root;
  panel = root.querySelector("#cet6-panel");
  const requested = ctx.query.get("tab");
  const initial = requested && TABS[requested] ? requested : "listening";
  for (const button of root.querySelectorAll(".cet6-tab")) {
    button.addEventListener("click", () => {
      if (button.dataset.tab !== active) switchTab(button.dataset.tab, ctx);
    });
  }
  await switchTab(initial, ctx);
}

export function unmount() {
  if (cleanup) {
    try { cleanup(); } catch { /* 忽略 */ }
    cleanup = null;
  }
  active = "";
  root = null;
  panel = null;
}
