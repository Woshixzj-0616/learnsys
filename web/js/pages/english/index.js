// 英语聚合页：精听 / 写作·翻译 / 每日积累 / 复习。
// 旧模块仍可用 #/cet6、#/daily、#/english-review 直达；这里只做收口，不改数据口径。
import { mountListening } from "../cet6/listening.js";
import { toast } from "../../ui.js";

const TABS = {
  listening: "精听",
  writing: "写作 / 翻译",
  daily: "每日积累",
  review: "复习",
};
const SUBTABS = { writing: "写作", translation: "翻译" };
const SUBTITLES = {
  listening: "原精听工作台：试卷、断点、回听与分析；每句可单独听写",
  writing: "写作与翻译：题库、限时练习、批改与二稿",
  daily: "写作句型 + 翻译短语 + 你自己的纠音点，每天一小份",
  review: "听辨/写作/翻译的到期错误卡，按记忆曲线复习",
};

let root = null;
let panel = null;
let cleanup = null;
let subCleanup = null;
let active = "";
let subActive = "";
let reviewKind = "sentence";

function markTabs(tab) {
  for (const button of root?.querySelectorAll(".english-tab") || []) {
    const on = button.dataset.tab === tab;
    button.classList.toggle("active", on);
    button.setAttribute("aria-selected", on ? "true" : "false");
  }
}

function markSubTabs(sub) {
  for (const button of panel?.querySelectorAll(".english-subtab") || []) {
    const on = button.dataset.sub === sub;
    button.classList.toggle("active", on);
    button.setAttribute("aria-selected", on ? "true" : "false");
  }
}

// 刷新后保持当前 tab：只改 hash，不触发 hashchange，交给本页自己切。
function rememberTab(tab, sub) {
  try {
    const params = new URLSearchParams();
    params.set("tab", tab);
    if (tab === "writing") params.set("sub", sub || subActive || "writing");
    if (tab === "review") params.set("kind", reviewKind);
    history.replaceState(null, "", `#/english?${params.toString()}`);
  } catch {
    // 地址栏改不了不影响页面
  }
}

function setReviewKind(kind) {
  reviewKind = kind === "word" ? "word" : "sentence";
  rememberTab("review");
}

function teardown() {
  const fn = cleanup;
  cleanup = null;
  if (fn) {
    try { fn(); } catch { /* 页面自己收尾失败不影响换标签 */ }
  }
  subCleanup = null;
  subActive = "";
  if (panel) panel.innerHTML = "";
}

async function switchTab(tab, ctx) {
  if (!TABS[tab]) tab = "listening";
  if (tab === active && cleanup) return;
  teardown();
  active = tab;
  markTabs(tab);
  rememberTab(tab);
  ctx.setSub(SUBTITLES[tab]);
  ctx.setActions("");

  if (tab === "listening") {
    const query = new URLSearchParams(ctx.query);
    query.delete("tab");
    query.delete("sub");
    query.delete("kind");
    cleanup = mountListening(panel, query);
    return;
  }
  if (tab === "writing") {
    await mountWriting(ctx, initialSub(ctx));
    return;
  }
  if (tab === "daily") {
    await mountDaily(ctx);
    return;
  }
  if (tab === "review") {
    await mountReview(ctx);
  }
}

async function mountWriting(ctx, sub) {
  panel.innerHTML = `
    <div class="english-subtabs" role="tablist" aria-label="写作与翻译">
      <button class="english-subtab" type="button" role="tab" data-sub="writing">写作</button>
      <button class="english-subtab" type="button" role="tab" data-sub="translation">翻译</button>
    </div>
    <div class="english-subpanel" id="english-subpanel"></div>`;
  for (const button of panel.querySelectorAll(".english-subtab")) {
    button.addEventListener("click", () => {
      if (button.dataset.sub !== subActive) {
        switchSub(button.dataset.sub, ctx)
          .catch((error) => toast(error.message || "页面没打开", "err"));
      }
    });
  }
  await switchSub(sub, ctx);
  if (active !== "writing") return;
  cleanup = () => {
    if (subCleanup) {
      try { subCleanup(); } catch { /* 同上 */ }
      subCleanup = null;
    }
  };
}

async function switchSub(sub, ctx) {
  if (!SUBTABS[sub]) sub = "writing";
  if (sub === subActive && subCleanup) return;
  if (subCleanup) {
    try { subCleanup(); } catch { /* 同上 */ }
    subCleanup = null;
  }
  subActive = sub;
  markSubTabs(sub);
  rememberTab("writing", sub);
  const host = panel?.querySelector("#english-subpanel");
  if (!host) return;
  host.innerHTML = "";
  const page = await import(
    sub === "translation" ? "../cet6/translation.js" : "../cet6/writing.js");
  if (active !== "writing" || subActive !== sub || !host.isConnected) return;
  const result = await page.mount({ panel: host, ctx });
  if (active !== "writing" || subActive !== sub) return;
  if (typeof result === "function") subCleanup = result;
}

// 复用旧页面：把它的 HTML 装进 panel，再把 ctx.root 指过去。
async function loadPageHtml(entry) {
  const response = await fetch(`/web/${entry}?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`页面没加载出来（${response.status}）`);
  return response.text();
}

async function mountReview(ctx) {
  const html = await loadPageHtml("pages/english-review.html");
  if (active !== "review" || !panel?.isConnected) return;
  panel.innerHTML = html;
  const page = await import("../english-review.js");
  if (active !== "review" || !panel?.isConnected) return;
  const query = new URLSearchParams({ kind: reviewKind });
  await page.mount({ ...ctx, root: panel, query, onKind: setReviewKind });
  if (active !== "review" || !panel?.isConnected) return;
  cleanup = () => { panel.innerHTML = ""; };
}

async function mountDaily(ctx) {
  const html = await loadPageHtml("pages/daily.html");
  if (active !== "daily" || !panel?.isConnected) return;
  panel.innerHTML = html;
  const page = await import("../daily.js");
  if (active !== "daily" || !panel?.isConnected) return;
  const result = await page.mount({ ...ctx, root: panel });
  if (active !== "daily" || !panel?.isConnected) return;
  cleanup = typeof result === "function" ? result : () => { panel.innerHTML = ""; };
}

function initialSub(ctx) {
  const requested = ctx.query.get("sub");
  return SUBTABS[requested] ? requested : "writing";
}

export async function mount(ctx) {
  root = ctx.root;
  panel = root.querySelector("#english-panel");
  subCleanup = null;
  subActive = "";
  reviewKind = ctx.query.get("kind") === "word" ? "word" : "sentence";
  const requested = ctx.query.get("tab");
  const initial = requested && TABS[requested] ? requested : "listening";
  for (const button of root.querySelectorAll(".english-tab")) {
    button.addEventListener("click", () => {
      if (button.dataset.tab !== active) {
        switchTab(button.dataset.tab, ctx)
          .catch((error) => toast(error.message || "页面没打开", "err"));
      }
    });
  }
  await switchTab(initial, ctx);
}

export function unmount() {
  teardown();
  active = "";
  root = null;
  panel = null;
}
