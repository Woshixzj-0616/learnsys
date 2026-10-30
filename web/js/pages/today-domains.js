// 今日页三域卡：学习 / 工作 / 生活。数据来自 /api/home，入口 href 也由服务端给，
// Web 与 Qt 读同一份 `learning.href / work.href / life.href`，不各写一套深链。
import { plain } from "../markdown.js";
import { escapeHtml } from "../ui.js";

function shortText(value, limit = 40) {
  const text = String(value || "").split(/\s+/).filter(Boolean).join(" ");
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

export function renderDomains(home) {
  const root = document.getElementById("domain-grid");
  if (!root) return;
  if (!home) {
    root.hidden = true;
    return;
  }

  const learning = home.learning || {};
  const work = home.work || {};
  const life = home.life || {};
  const wrong = (learning.recent_wrong || [])[0];
  const nextStep = work.next_step
    || (work.projects || []).find((item) => item.next_step)?.next_step || "";
  const reminder = (life.reminders || [])[0] || "";

  const cards = [
    {
      key: "learn",
      label: "学习",
      href: learning.href || "#/cet6",
      title: `今日 ${Number(learning.done || 0)}/${Number(learning.total || 3)}`
        + ` · 到期复习 ${Number(learning.due_reviews || 0)}`,
      sub: wrong ? `最近卡点：${plain(wrong.question, 40)}` : "最近卡点：暂无",
    },
    {
      key: "work",
      label: "工作",
      href: work.href || "#/agents",
      title: `进行中 ${Number(work.running || 0)} · 待排队 ${Number(work.queued || 0)}`,
      sub: nextStep ? `下一步：${shortText(nextStep)}` : "下一步：暂无",
    },
    {
      key: "life",
      label: "生活",
      href: life.href || "#/life",
      title: `待办 ${Number(life.item_count || 0)}`
        + ` · 卡片 ${Number(life.card_count || 0)}`,
      sub: reminder ? `提醒：${shortText(reminder)}` : "提醒：暂无",
    },
  ];

  root.innerHTML = cards.map((card) => `
    <a class="domain-card" data-domain="${card.key}" href="${escapeHtml(card.href)}">
      <span class="domain-label">${escapeHtml(card.label)}</span>
      <span class="domain-title">${escapeHtml(card.title)}</span>
      <span class="domain-sub">${escapeHtml(card.sub)}</span>
    </a>`).join("");
  root.hidden = false;
}
