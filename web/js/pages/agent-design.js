// Agent 设计页：设计原则 / 机制卡片 / 自测三个子 tab。
// 内容在 agent-design-data.js；横向对照放在每条原则 / 每张机制卡里，不单开表。
import { escapeHtml } from "../ui.js";
import { MECHANISMS, PRINCIPLES, QUESTIONS } from "./agent-design-data.js";

const STAGES = [
  ["输入", "ask"], ["意图", "intent"], ["工具", "tool"], ["证据", "evidence"],
  ["打回", "nudge"], ["作答", "stream"], ["审核", "audit"], ["记忆", "memory"], ["评估", "eval"],
];

const PANELS = {
  principles: "ad-panel-principles",
  mechanisms: "ad-panel-mechanisms",
  quiz: "ad-panel-quiz",
};

let root = null;
let currentDetail = null;

function showNow(detail) {
  const box = document.getElementById("ad-now");
  if (!box) return;
  if (!detail) {
    box.innerHTML = "还没展开卡片。点开一张原则卡或机制卡。";
    return;
  }
  if (detail.classList.contains("ad-card")) {
    const title = detail.querySelector(".ad-t")?.textContent || "";
    const one = detail.querySelector(".ad-o")?.textContent || "";
    const trace = detail.querySelector(".ad-tag")?.textContent || "";
    box.innerHTML = `<b>机制：</b>${escapeHtml(title)}<br>${escapeHtml(one)}` +
      (trace ? `<br><span class="ad-tag">trace：${escapeHtml(trace)}</span>` : "");
  } else {
    const title = detail.querySelector("summary b")?.textContent || "";
    const one = detail.querySelector("summary span")?.textContent || "";
    box.innerHTML = `<b>原则：</b>${escapeHtml(title)}<br>${escapeHtml(one)}`;
  }
}

function bindNow() {
  for (const detail of root?.querySelectorAll(".ad-card, .ad-principle") || []) {
    detail.addEventListener("toggle", () => {
      if (detail.open) {
        currentDetail = detail;
        showNow(detail);
      } else if (currentDetail === detail) {
        currentDetail = null;
        const next = root?.querySelector(".ad-card[open], .ad-principle[open]");
        showNow(next || null);
      }
    });
  }
}

function markSubtabs(tab) {
  for (const button of root?.querySelectorAll(".ad-subtab") || []) {
    const on = button.dataset.adTab === tab;
    button.classList.toggle("on", on);
    button.setAttribute("aria-selected", on ? "true" : "false");
  }
}

function switchPanel(tab, remember = true) {
  if (!PANELS[tab]) tab = "principles";
  for (const [key, id] of Object.entries(PANELS)) {
    const panel = document.getElementById(id);
    if (panel) panel.hidden = key !== tab;
  }
  markSubtabs(tab);
  if (remember) {
    try {
      history.replaceState(null, "", `#/travel-agent?tab=design&sub=${tab}`);
    } catch {
      // 地址栏改不了不影响页面
    }
  }
}

function renderMap() {
  const box = document.getElementById("ad-map");
  if (!box) return;
  box.innerHTML = STAGES.map(([label, id], index) =>
    `${index ? '<span class="ad-arrow">→</span>' : ""}<span class="ad-stage"><a href="#ad-${escapeHtml(id)}" data-mechanism="${escapeHtml(id)}">${escapeHtml(label)}</a></span>`).join("");
}

function openMechanism(id) {
  switchPanel("mechanisms");
  const card = document.getElementById(`ad-${id}`);
  if (!card) return;
  card.open = true;
  card.scrollIntoView({ block: "start", behavior: "smooth" });
}

function renderCards() {
  const box = document.getElementById("ad-cards");
  if (!box) return;
  const groups = [];
  for (const item of MECHANISMS) {
    let group = groups.find((one) => one.name === item.group);
    if (!group) {
      group = { name: item.group, items: [] };
      groups.push(group);
    }
    group.items.push(item);
  }
  box.innerHTML = groups.map((group) => `
    <div class="ad-group">${escapeHtml(group.name)}</div>
    <div class="ad-grid">${group.items.map((item) => `
      <details class="ad-card" id="ad-${escapeHtml(item.id)}">
        <summary>
          <div class="ad-t">${escapeHtml(item.title)}</div>
          <div class="ad-o">${escapeHtml(item.one)}</div>
        </summary>
        <div class="ad-body">
          <div class="ad-row"><b>解决什么：</b>${escapeHtml(item.problem)}</div>
          <div class="ad-row"><b>不这么做会怎样：</b>${escapeHtml(item.failure)}</div>
          <div class="ad-row"><b>代码落点：</b><div class="ad-code">${item.code.map((one) => `<span>${escapeHtml(one)}</span>`).join("")}</div></div>
          <div class="ad-row"><b>trace 里看：</b><span class="ad-tag">${escapeHtml(item.trace)}</span></div>
          <div class="ad-row"><b>取舍：</b>${escapeHtml(item.tradeoff)}</div>
          <div class="ad-row"><b>业内不同做法：</b><div class="ad-approaches">${item.approaches.map(([name, example, note]) => `
            <div class="ad-approach"><b>${escapeHtml(name)}</b><span>${escapeHtml(example)}</span><em>${escapeHtml(note)}</em></div>`).join("")}</div></div>
          <div class="ad-row"><b>设计要点：</b>${escapeHtml(item.design)}</div>
        </div>
      </details>`).join("")}</div>`).join("");
}

function renderPrinciples() {
  const box = document.getElementById("ad-principles");
  if (!box) return;
  box.innerHTML = PRINCIPLES.map((item, index) => `
    <details class="ad-principle">
      <summary>
        <b>${index + 1}. ${escapeHtml(item.title)}</b>
        <span>${escapeHtml(item.one)}</span>
      </summary>
      <div class="ad-body">
        <div class="ad-row"><b>为什么：</b>${escapeHtml(item.why)}</div>
        <div class="ad-row"><b>不这么做会怎样：</b>${escapeHtml(item.failure)}</div>
        <div class="ad-row"><b>业内不同做法：</b><div class="ad-approaches">${item.industry.map(([name, example]) => `
          <div class="ad-approach"><b>${escapeHtml(name)}</b><span>${escapeHtml(example)}</span></div>`).join("")}</div></div>
      </div>
    </details>`).join("");
}

function renderQuiz() {
  const box = document.getElementById("ad-quiz");
  if (!box) return;
  box.innerHTML = QUESTIONS.map(([q, a], index) =>
    `<details class="ad-q"><summary>Q${index + 1}. ${escapeHtml(q)}</summary><div>${escapeHtml(a)}</div></details>`).join("");
}

export async function mount(ctx) {
  ctx.setSub("设计原则 + 机制卡片；每张卡里都带业内不同做法和举例。");
  root = ctx.root;
  renderMap();
  renderPrinciples();
  renderCards();
  renderQuiz();
  bindNow();
  showNow(null);
  for (const button of root.querySelectorAll(".ad-subtab")) {
    button.addEventListener("click", () => switchPanel(button.dataset.adTab));
  }
  for (const link of root.querySelectorAll("[data-mechanism]")) {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      openMechanism(link.dataset.mechanism);
    });
  }
  const requested = ctx.query?.get?.("sub");
  switchPanel(PANELS[requested] ? requested : "principles", false);
}

export function unmount() {
  root = null;
}
