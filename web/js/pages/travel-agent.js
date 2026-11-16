// 智能旅行 Agent：把「Agent 设计」和「调用路径」合成一个入口，并挂内置 AI 圆圈。
// 两个子页仍住在 agent-design.js / agent-trace.js；这里只做 tab 切换、上下文与 AI 装配。
import { mount as mountDesign, unmount as unmountDesign } from "./agent-design.js";
import { mount as mountTrace, unmount as unmountTrace } from "./agent-trace.js";
import {
  clearContextProvider, mount as mountAI, setContextProvider, setEnabled, setPage,
} from "./english/ai.js";

const TABS = {
  design: {
    html: "agent-design",
    title: "Agent 设计",
    sub: "机制、取舍与设计原则；每个机制都带代码落点和真实事故。",
  },
  trace: {
    html: "agent-trace",
    title: "调用路径",
    sub: "输入一句话发给智能旅行 agent，或从左边选一条历史请求看它的调用路径。",
  },
};

let root = null;
let panel = null;
let cleanup = null;
let cleanupAI = null;
let active = "";

function markTabs(tab) {
  for (const button of root?.querySelectorAll(".ta-tab") || []) {
    const on = button.dataset.taTab === tab;
    button.classList.toggle("on", on);
    button.setAttribute("aria-selected", on ? "true" : "false");
  }
}

function rememberTab(tab) {
  try {
    history.replaceState(null, "", `#/travel-agent?tab=${tab}`);
  } catch {
    // 地址栏改不了不影响页面
  }
}

function teardown() {
  if (cleanup) {
    try { cleanup(); } catch { /* 子页自己收尾失败不影响切 tab */ }
    cleanup = null;
  }
  if (panel) panel.innerHTML = "";
}

async function loadHtml(name) {
  const response = await fetch(`/web/pages/${name}.html?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`页面没加载出来（${response.status}）`);
  return response.text();
}

function provider() {
  if (active === "design") {
    const sub = panel?.querySelector(".ad-subtab.on")?.dataset.adTab || "principles";
    const card = panel?.querySelector(".ad-card[open]");
    const principle = panel?.querySelector(".ad-principle[open]");
    const mechanism = card ? card.id.replace(/^ad-/, "") : "overview";
    const title = card?.querySelector(".ad-t")?.textContent || "";
    const detail = card?.querySelector(".ad-body")?.innerText || "";
    const principleTitle = principle?.querySelector("summary b")?.textContent || "";
    const principleDetail = principle?.querySelector(".ad-body")?.innerText || "";
    const names = [...(panel?.querySelectorAll(".ad-card .ad-t") || [])]
      .map((node) => node.textContent).filter(Boolean);
    return {
      object_type: "agent_design",
      object_id: mechanism,
      title: `智能旅行 Agent · Agent 设计（${sub}）`,
      surrounding: {
        tab: "design",
        sub,
        mechanism,
        mechanism_title: title,
        mechanism_detail: detail.slice(0, 1800),
        principle_title: principleTitle,
        principle_detail: principleDetail.slice(0, 1200),
        mechanisms: names,
      },
      learning_state: { open_cards: panel?.querySelectorAll(".ad-card[open]").length || 0 },
    };
  }
  const row = panel?.querySelector(".at-row.on");
  const question = row?.querySelector(".at-q")?.textContent || "";
  const stats = {};
  panel?.querySelectorAll(".at-stat").forEach((node) => {
    const key = node.querySelector(".k")?.textContent;
    const value = node.querySelector(".v")?.textContent;
    if (key) stats[key] = value;
  });
  const spans = {};
  panel?.querySelectorAll(".at-bar-row").forEach((node) => {
    const cells = node.querySelectorAll("span");
    if (cells.length >= 3) spans[cells[0].textContent] = cells[2].textContent;
  });
  const path = [...(panel?.querySelectorAll(".at-node") || [])]
    .map((node) => node.innerText.replace(/\s+/g, " ").trim()).filter(Boolean);
  const detail = panel?.querySelector(".at-detail")?.innerText || "";
  return {
    object_type: "agent_trace",
    object_id: row?.dataset.id || "",
    title: "智能旅行 Agent · 调用路径",
    surrounding: {
      tab: "trace",
      question,
      summary: stats,
      spans,
      path,
      detail: detail.slice(0, 2200),
    },
    learning_state: { selected_trace: row?.dataset.id || "" },
  };
}

async function switchTab(tab, ctx) {
  if (!TABS[tab]) tab = "design";
  if (tab === active && cleanup) return;
  teardown();
  active = tab;
  markTabs(tab);
  rememberTab(tab);
  ctx.setSub(TABS[tab].sub);
  panel.innerHTML = `<div class="ta-loading">正在打开 ${TABS[tab].title}…</div>`;
  try {
    panel.innerHTML = await loadHtml(TABS[tab].html);
    if (active !== tab) return;
    if (tab === "design") {
      await mountDesign({ ...ctx, root: panel });
      cleanup = () => unmountDesign();
    } else {
      await mountTrace({ ...ctx, root: panel });
      cleanup = () => unmountTrace();
    }
    if (active !== tab) return;
    setPage(tab);
    setContextProvider(provider);
  } catch (error) {
    panel.innerHTML = `<div class="ta-loading">页面没打开：${error?.message || error}</div>`;
  }
}

export async function mount(ctx) {
  root = ctx.root;
  panel = root.querySelector("#ta-panel");
  cleanupAI = mountAI(root, {
    title: "智能旅行 AI",
    surface: "travel",
    module: "travel",
    page: "travel_agent",
    titlePrefix: "智能旅行 Agent",
    convKey: "learnsys_travel_ai_conv",
    overlay: true,
  });
  setEnabled(true);
  for (const button of root.querySelectorAll(".ta-tab")) {
    button.addEventListener("click", () => {
      if (button.dataset.taTab !== active) {
        switchTab(button.dataset.taTab, ctx)
          .catch((error) => { panel.innerHTML = `<div class="ta-loading">${error?.message || error}</div>`; });
      }
    });
  }
  const requested = ctx.query?.get?.("tab");
  await switchTab(TABS[requested] ? requested : "design", ctx);
}

export function unmount() {
  teardown();
  clearContextProvider();
  setEnabled(false);
  if (cleanupAI) {
    try { cleanupAI(); } catch { /* 忽略 */ }
    cleanupAI = null;
  }
  active = "";
  root = null;
  panel = null;
}
