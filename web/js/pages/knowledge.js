// 知识点：8 个类目的答题流水、正确率与最近答题；旧错题回填只展示。
import { api } from "../api.js";
import { escapeHtml, relative, toast } from "../ui.js";

let days = 0;
let dataset = null;
let selected = null;
let nodes = {};

function pct(value) {
  return value == null ? "—" : `${Math.round(Number(value) * 100)}%`;
}

function masteryPct(value) {
  if (value == null) return "—";
  // 向下取整并 cap 99%：69.9% 不显示成 70%，99.6% 不显示成 100%。
  return `${Math.min(99, Math.floor(Number(value) * 100 + 1e-9))}%`;
}

function levelClass(level) {
  return {
    "掌握": "mastered",
    "在学": "learning",
    "薄弱": "weak",
    "样本不足": "pending",
    "未开始": "none",
    "不建模": "none",
  }[level] || "none";
}

function statChip(label, value, extra = "") {
  return `<div class="review-chip${extra}"><span>${escapeHtml(label)}</span>` +
    `<strong>${escapeHtml(String(value))}</strong></div>`;
}

function renderStats() {
  const totals = dataset?.totals || {};
  const points = dataset?.points || [];
  const modeled = points.filter((point) => point.mastery_level !== "不建模").length;
  const chips = [
    statChip("总作答", totals.attempts ?? 0),
    statChip("测验正确率", pct(totals.accuracy)),
    statChip("平均掌握度", masteryPct(totals.average_mastery)),
    statChip("已建模类目", `${totals.mastery_ready_points ?? 0}/${modeled}`),
    statChip("可入 BKT", totals.bkt_ready ?? 0),
    statChip("回填", totals.backfill ?? 0),
  ];
  if (Number(totals.parse_failed || 0) > 0) {
    chips.push(statChip("格式异常", totals.parse_failed, " warn"));
  }
  nodes.stats.innerHTML = chips.join("");
}

function pointState(point) {
  if (point.mastery_level) return point.mastery_level;
  // 旧后端没有掌握度字段时的回退，避免前后端版本错配整页空白。
  if (Number(point.quiz_known || 0) < 5) return "样本不足";
  if (point.accuracy != null && Number(point.accuracy) < 0.6) return "偏弱";
  return "观察中";
}

function masteryMeta(point) {
  if (point.mastery_ready) return `掌握度 ${masteryPct(point.mastery)}`;
  if (Number(point.mastery_attempts || 0) > 0) {
    return `样本不足 ${point.mastery_attempts}/5`;
  }
  return "";
}

function renderList() {
  const points = dataset?.points || [];
  if (!points.length) {
    nodes.list.innerHTML = '<div class="empty">还没有知识点数据。</div>';
    return;
  }
  nodes.list.innerHTML = points.map((point) => {
    const active = Number(selected) === Number(point.id) ? " active" : "";
    const extras = [];
    extras.push(`${point.attempts || 0} 次`);
    extras.push(`正确率 ${pct(point.accuracy)}`);
    const mastery = masteryMeta(point);
    if (mastery) extras.push(mastery);
    extras.push(`可入 BKT ${point.bkt_ready || 0}`);
    if (Number(point.backfill || 0) > 0) extras.push(`回填 ${point.backfill}`);
    const last = point.last_ts ? `最近 ${relative(point.last_ts)}` : "还没练过";
    const level = pointState(point);
    return `<button type="button" class="knowledge-row${active}" data-point="${point.id}">
      <span class="knowledge-row-name">${escapeHtml(point.name)}</span>
      <span class="knowledge-row-meta">${escapeHtml(extras.join(" · "))}</span>
      <span class="knowledge-row-tail"><span class="knowledge-state ${levelClass(level)}">${escapeHtml(level)}</span>
        <span class="hint">${escapeHtml(last)}</span></span>
    </button>`;
  }).join("");
}

function attemptBadge(item) {
  if (item.correct === true) return '<span class="knowledge-badge ok">正确</span>';
  if (item.correct === false) return '<span class="knowledge-badge bad">错误</span>';
  return '<span class="knowledge-badge unknown">未判定</span>';
}

function renderAttempts(data) {
  const title = data?.point?.name || "选一个类目";
  nodes.detailTitle.textContent = title;
  nodes.detailCount.textContent = data ? `共 ${data.count} 条` : "";
  const items = data?.items || [];
  if (!items.length) {
    nodes.attempts.innerHTML = '<div class="empty">这个类目还没有答题记录。</div>';
    return;
  }
  const html = items.map((item) => {
    const source = item.source === "backfill"
      ? '<span class="knowledge-badge backfill">回填 · 仅展示</span>'
      : '<span class="knowledge-badge">测验</span>';
    const feedbackLabel = item.source === "backfill" ? "参考答案" : "批改";
    const points = (item.points || [])
      .map((name) => `<span class="knowledge-chip">${escapeHtml(name)}</span>`).join("");
    const answer = item.my_answer
      ? `<p class="knowledge-line"><b>我的作答：</b>${escapeHtml(item.my_answer.slice(0, 240))}</p>`
      : '<p class="knowledge-line hint">未记录作答</p>';
    const feedback = item.feedback
      ? `<p class="knowledge-line"><b>${feedbackLabel}：</b>${escapeHtml(item.feedback.slice(0, 240))}</p>`
      : "";
    return `<article class="knowledge-attempt">
      <div class="knowledge-attempt-head">
        ${attemptBadge(item)} ${source}
        <span class="hint">${escapeHtml(relative(item.ts))}</span>
      </div>
      <p class="knowledge-question">${escapeHtml((item.question || "").slice(0, 300))}</p>
      ${answer}
      ${feedback}
      <div class="knowledge-points">${points}</div>
    </article>`;
  }).join("");
  const more = data.count > items.length
    ? `<p class="hint">只显示最近 ${items.length} 条。</p>` : "";
  nodes.attempts.innerHTML = html + more;
}

function renderDetailMastery(point) {
  const node = nodes.detailMastery;
  if (!node) return;
  if (!point || !point.mastery_level) {
    node.textContent = "";
    return;
  }
  if (point.mastery_level === "不建模") {
    node.textContent = "「其他」是兜底类目，只记录答题，不估算掌握度。";
    return;
  }
  const attempts = Number(point.mastery_attempts || 0);
  const minSamples = Number(dataset?.bkt?.min_samples || 5);
  if (point.mastery_ready) {
    node.textContent = `${point.mastery_level} · 掌握度 ${masteryPct(point.mastery)}` +
      ` · 基于 ${attempts} 次可建模答题`;
    return;
  }
  if (attempts <= 0) {
    node.textContent = "还没有可建模答题。";
    return;
  }
  node.textContent = `样本不足 ${attempts}/${minSamples} · ` +
    `再答 ${Math.max(0, minSamples - attempts)} 次可估算掌握度`;
}

async function selectPoint(pointId) {
  selected = Number(pointId);
  renderList();
  const point = (dataset?.points || []).find(
    (item) => Number(item.id) === selected);
  renderDetailMastery(point);
  try {
    const data = await api.get(
      `/api/knowledge/${selected}/attempts?days=${days}&limit=20`);
    renderAttempts(data);
  } catch (error) {
    nodes.attempts.innerHTML =
      `<div class="review-error">${escapeHtml(error.message || "读取失败")}</div>`;
  }
}

async function load() {
  try {
    dataset = await api.get(`/api/knowledge?days=${days}`);
    renderStats();
    renderList();
    const has = dataset.points?.some((point) => Number(point.id) === Number(selected));
    if (has) {
      await selectPoint(selected);
    } else {
      nodes.detailTitle.textContent = "选一个类目";
      nodes.detailCount.textContent = "";
      renderDetailMastery(null);
    }
  } catch (error) {
    nodes.list.innerHTML =
      `<div class="review-error">${escapeHtml(error.message || "读取失败")}</div>`;
  }
}

async function backfill() {
  const button = nodes.backfill;
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = "正在检查…";
  try {
    const dry = await api.post("/api/knowledge/backfill", {dry_run: true});
    if (dry.already_done) {
      toast("旧错题已经回填过了");
      return;
    }
    if (!dry.created) {
      toast("没有需要回填的旧错题");
      return;
    }
    const ok = confirm(
      `将回填 ${dry.created} 条旧错题（仅展示，不计入 BKT 样本）。继续吗？`);
    if (!ok) return;
    button.textContent = "正在回填…";
    const done = await api.post("/api/knowledge/backfill", {dry_run: false});
    toast(`已回填 ${done.created || 0} 条旧错题`);
    await load();
  } catch (error) {
    toast(error.message || "回填失败", "err");
  } finally {
    button.disabled = false;
    button.textContent = "回填旧错题";
  }
}

export async function mount(ctx) {
  ctx.setSub("每次测验作答（含答对）按 8 个类目落库；回填只展示");
  ctx.setActions('<a class="btn" href="#/quiz">去测验</a>');
  days = 0;
  selected = null;
  dataset = null;
  nodes = {
    stats: ctx.root.querySelector("#knowledge-stats"),
    list: ctx.root.querySelector("#knowledge-list"),
    attempts: ctx.root.querySelector("#knowledge-attempts"),
    detailTitle: ctx.root.querySelector("#knowledge-detail-title"),
    detailCount: ctx.root.querySelector("#knowledge-detail-count"),
    detailMastery: ctx.root.querySelector("#knowledge-detail-mastery"),
    backfill: ctx.root.querySelector("#knowledge-backfill"),
  };
  ctx.root.querySelectorAll(".knowledge-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      days = Number(tab.dataset.days || 0);
      ctx.root.querySelectorAll(".knowledge-tab").forEach((node) => {
        node.classList.toggle("active", node === tab);
      });
      load();
    });
  });
  nodes.list.addEventListener("click", (event) => {
    const row = event.target.closest("button[data-point]");
    if (row) selectPoint(Number(row.dataset.point));
  });
  nodes.backfill.addEventListener("click", backfill);
  await load();
}
