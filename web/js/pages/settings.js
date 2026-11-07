// 设置页：读掩码配置、保存、测连接、备份、模块开关。
import { api } from "../api.js";
import { bindMemory, loadCandidates, loadMemories, loadProfileStatus } from "./settings-memory.js";
import { escapeHtml, toast } from "../ui.js";

let ctxRef = null;
let current = null;
let dirty = false;
let localRoots = [];

export async function mount(ctx) {
  ctxRef = ctx;
  dirty = false;
  ctx.setSub("改完保存；热键与备份目录重启后生效");
  ctx.setActions('<button class="btn btn-primary" type="button" id="save-top">保存设置</button>');

  try {
    current = await api.get("/api/settings");
  } catch (error) {
    ctx.root.querySelector(".settings-page").innerHTML =
      `<div class="empty"><strong>设置没读出来</strong>${escapeHtml(error.message || error)}</div>`;
    return;
  }
  fill(current);
  bind();
  loadLocalIndex();
  loadMemories();
  loadCandidates();
  loadProfileStatus();
}

function fill(data) {
  setValue("agent-base", data.agent?.base_url);
  setValue("agent-model", data.agent?.model);
  setValue("agent-fast", data.agent?.fast_model);
  setValue("agent-strong", data.agent?.strong_model);
  setValue("agent-auto-route", data.agent?.auto_route || "off");
  setValue("agent-tokens", data.agent?.max_tokens);
  setValue("agent-speed", data.agent?.speed || "balanced");
  setValue("price-input", data.agent?.price_input ?? "");
  setValue("price-output", data.agent?.price_output ?? "");
  setValue("price-cache", data.agent?.price_cache_read ?? "");
  setValue("price-currency", data.agent?.currency || "USD");
  setValue("daily-cost-limit", data.agent?.daily_cost_limit ?? 0);
  setValue("daily-call-limit", data.agent?.daily_call_limit ?? 0);
  renderPrices(data.agent?.prices || {});
  document.getElementById("agent-token").value = "";
  document.getElementById("agent-token-hint").textContent = keyHint(
    data.agent?.auth_token_set, data.agent?.auth_token_mask, data.agent?.auth_token_source);

  setValue("vision-base", data.vision?.base_url);
  setValue("vision-model", data.vision?.model);
  document.getElementById("vision-key").value = "";
  document.getElementById("vision-key-hint").textContent = keyHint(
    data.vision?.api_key_set, data.vision?.api_key_mask, data.vision?.api_key_source);

  setValue("hotkey", data.hotkey || "");
  setValue("weekly-goal-days", data.weekly_goal_days ?? 5);
  setValue("briefing-time", data.briefing?.generate_at || "07:30");
  const briefingEnabled = document.getElementById("briefing-enabled");
  if (briefingEnabled) briefingEnabled.checked = data.briefing?.enabled !== false;
  document.getElementById("data-root").value = data.data_root || "";
  document.getElementById("settings-path").textContent = `设置在：${data.settings_path || ""}`;
  document.getElementById("backup-dir").textContent = `备份目录：${data.backup_dir || ""}`;
  localRoots = Array.isArray(data.materials?.import_dirs)
    ? data.materials.import_dirs.map((item) => String(item)).filter(Boolean) : [];
  renderLocalRoots();

  const container = document.getElementById("module-toggles");
  const modules = ctxRef.registry || [];
  container.innerHTML = modules.map((module) => {
    const checked = data.modules?.[module.id] !== false ? "checked" : "";
    return `<label class="toggle-row">
      <input type="checkbox" data-module="${escapeHtml(module.id)}" ${checked}>
      ${escapeHtml(module.name)}
      ${module.status === "planned" ? '<span class="hint">（待建）</span>' : ""}
    </label>`;
  }).join("");

  container.querySelectorAll("input").forEach((node) => {
    node.addEventListener("input", markDirty);
    node.addEventListener("change", markDirty);
  });
}

function keyHint(has, mask, source) {
  if (!has) return "未配置";
  if (source === "agent") return `跟随主模型 key：${mask || "••••"}（留空不改）`;
  const where = source === "env" ? "来自环境变量" : "已保存在设置文件";
  return `${where}：${mask || "••••"}（留空不改）`;
}

function renderLocalRoots() {
  const box = document.getElementById("local-roots");
  if (!box) return;
  if (!localRoots.length) {
    box.innerHTML = '<span class="local-root-empty">还没有目录；agent 暂时读不了本机文件。</span>';
    return;
  }
  box.innerHTML = localRoots.map((path) => `
    <div class="local-root-row">
      <code>${escapeHtml(path)}</code>
      <button class="btn" type="button" data-local-root="${escapeHtml(path)}">移除</button>
    </div>`).join("");
}

const INDEX_STATUS_LABELS = {
  pending: "等待首次扫描",
  missing: "目录暂时不可用",
  truncated: "文件过多，只索引了前 20 万个",
  error: "扫描出错",
};

async function loadLocalIndex() {
  const node = document.getElementById("local-index-status");
  if (!node) return;
  try {
    const data = await api.get("/api/local-index");
    const roots = Array.isArray(data.roots) ? data.roots : [];
    if (!roots.length) {
      node.textContent = "还没有可读目录，索引为空。";
      node.title = "";
      return;
    }
    const stamps = roots.map((row) => String(row.scanned_at || "")).filter(Boolean).sort();
    const last = stamps.length ? stamps[stamps.length - 1].slice(11, 16) : "";
    let text = `已索引 ${Number(data.total || 0)} 个文件`;
    if (last) text += ` · 最后更新 ${last}`;
    if (data.scanning) text += " · 正在更新…";
    const bad = roots.filter((row) => row.status && row.status !== "ok");
    if (bad.length) text += `；${bad.length} 个目录异常`;
    node.textContent = text;
    node.title = bad.map((row) =>
      `${row.root}：${INDEX_STATUS_LABELS[row.status] || row.status}` +
      (row.note ? `（${row.note}）` : "")).join("\n");
  } catch (error) {
    node.textContent = `索引状态没读出来：${error.message || error}`;
    node.title = "";
  }
}

async function rebuildIndex() {
  const button = document.getElementById("local-index-rebuild");
  if (!button) return;
  button.disabled = true;
  try {
    const result = await api.post("/api/local-index/rebuild", {});
    toast(result.message || "已开始重建索引", "ok");
    setTimeout(loadLocalIndex, 1200);
    setTimeout(loadLocalIndex, 4000);
  } catch (error) {
    toast(error.message || "重建索引失败", "err");
  } finally {
    button.disabled = false;
  }
}

function setValue(id, value) {
  const node = document.getElementById(id);
  if (node) node.value = value ?? "";
}

function markDirty() {
  dirty = true;
  const note = document.getElementById("save-note");
  if (note) note.textContent = "有改动还没保存";
}

function bind() {
  const form = ctxRef.root.querySelector(".settings-page");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    save();
  });
  form.querySelectorAll("input, select").forEach((node) => {
    node.addEventListener("input", markDirty);
    node.addEventListener("change", markDirty);
  });

  document.getElementById("save-top").addEventListener("click", save);
  ctxRef.root.querySelector("#save-bottom").addEventListener("click", save);
  ctxRef.root.querySelector("#test-text").addEventListener("click", () => test("text"));
  ctxRef.root.querySelector("#test-vision").addEventListener("click", () => test("vision"));
  ctxRef.root.querySelector("#backup-now").addEventListener("click", backup);

  document.getElementById("price-add").addEventListener("click", () => {
    document.getElementById("price-models").appendChild(priceRow("", {}));
    markDirty();
  });
  const priceBox = document.getElementById("price-models");
  priceBox.addEventListener("click", (event) => {
    const button = event.target.closest("[data-price-remove]");
    if (!button) return;
    button.closest("[data-price-row]")?.remove();
    markDirty();
  });
  priceBox.addEventListener("input", markDirty);

  const rootInput = document.getElementById("local-root-input");
  const addRoot = () => {
    const value = rootInput.value.trim().replace(/^"|"$/g, "");
    if (!value) return;
    if (!localRoots.includes(value)) localRoots.push(value);
    rootInput.value = "";
    renderLocalRoots();
    markDirty();
  };
  document.getElementById("local-root-add").addEventListener("click", addRoot);
  rootInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addRoot();
    }
  });
  document.getElementById("local-roots").addEventListener("click", (event) => {
    const button = event.target.closest("[data-local-root]");
    if (!button) return;
    localRoots = localRoots.filter((item) => item !== button.dataset.localRoot);
    renderLocalRoots();
    markDirty();
  });
  document.getElementById("local-index-rebuild")
    ?.addEventListener("click", rebuildIndex);

  bindMemory();
}

function renderPrices(prices) {
  const box = document.getElementById("price-models");
  box.innerHTML = "";
  Object.entries(prices || {}).forEach(([model, price]) => {
    box.appendChild(priceRow(model, price || {}));
  });
}

function priceRow(model, price) {
  const row = document.createElement("div");
  row.className = "price-row";
  row.dataset.priceRow = "";
  const fields = [
    ["data-price-model", "text", model, "模型名"],
    ["data-price-in", "number", price.input ?? "", "输入价"],
    ["data-price-out", "number", price.output ?? "", "输出价"],
    ["data-price-cache", "number", price.cache_read ?? "", "缓存价"],
  ];
  for (const [attr, type, value, placeholder] of fields) {
    const input = document.createElement("input");
    input.className = "input";
    input.setAttribute(attr, "");
    input.type = type;
    if (type === "number") {
      input.min = "0";
      input.step = "0.001";
    }
    input.placeholder = placeholder;
    input.value = value ?? "";
    row.appendChild(input);
  }
  const remove = document.createElement("button");
  remove.className = "btn";
  remove.type = "button";
  remove.dataset.priceRemove = "";
  remove.textContent = "删除";
  row.appendChild(remove);
  return row;
}

function collectPrices() {
  const prices = {};
  document.querySelectorAll("#price-models [data-price-row]").forEach((row) => {
    const model = row.querySelector("[data-price-model]").value.trim();
    if (!model) return;
    const entry = {};
    for (const [attr, key] of [["data-price-in", "input"],
      ["data-price-out", "output"], ["data-price-cache", "cache_read"]]) {
      const raw = row.querySelector(`[${attr}]`).value;
      const value = Number(raw);
      if (raw !== "" && Number.isFinite(value) && value >= 0) entry[key] = value;
    }
    prices[model] = entry;
  });
  return prices;
}

function collect() {
  const agent = {
    base_url: valueOf("agent-base"),
    model: valueOf("agent-model"),
    fast_model: valueOf("agent-fast"),
    strong_model: valueOf("agent-strong"),
    auto_route: valueOf("agent-auto-route") || "off",
    speed: valueOf("agent-speed") || "balanced",
  };
  const tokens = Number(valueOf("agent-tokens"));
  if (Number.isFinite(tokens) && tokens > 0) agent.max_tokens = Math.round(tokens);
  for (const [id, key] of [["price-input", "price_input"],
    ["price-output", "price_output"], ["price-cache", "price_cache_read"]]) {
    const raw = valueOf(id);
    const value = Number(raw);
    if (raw !== "" && Number.isFinite(value) && value >= 0) agent[key] = value;
  }
  const currency = valueOf("price-currency");
  if (currency) agent.currency = currency;
  const costLimit = Number(valueOf("daily-cost-limit"));
  if (Number.isFinite(costLimit) && costLimit >= 0) agent.daily_cost_limit = costLimit;
  const callLimit = Number(valueOf("daily-call-limit"));
  if (Number.isFinite(callLimit) && callLimit >= 0) {
    agent.daily_call_limit = Math.round(callLimit);
  }
  agent.prices = collectPrices();
  const token = valueOf("agent-token");
  if (token) agent.auth_token = token;

  const vision = {
    base_url: valueOf("vision-base"),
    model: valueOf("vision-model"),
  };
  const visionKey = valueOf("vision-key");
  if (visionKey) vision.api_key = visionKey;

  const modules = {};
  ctxRef.root.querySelectorAll("[data-module]").forEach((node) => {
    modules[node.dataset.module] = node.checked;
  });
  const weeklyGoalDays = Number(valueOf("weekly-goal-days"));
  const briefing = {
    enabled: document.getElementById("briefing-enabled")?.checked !== false,
    generate_at: valueOf("briefing-time") || "07:30",
  };

  return {
    agent, vision, hotkey: valueOf("hotkey"), modules, briefing,
    materials: { import_dirs: localRoots.slice() },
    ...(Number.isFinite(weeklyGoalDays) && weeklyGoalDays >= 3 && weeklyGoalDays <= 7
      ? { weekly_goal_days: Math.round(weeklyGoalDays) } : {}),
  };
}

function valueOf(id) {
  return String(document.getElementById(id)?.value || "").trim();
}

async function save() {
  const note = document.getElementById("save-note");
  const buttons = [document.getElementById("save-top"), document.getElementById("save-bottom")];
  buttons.forEach((button) => { if (button) button.disabled = true; });
  note.textContent = "正在保存…";
  try {
    const payload = collect();
    const result = await api.post("/api/settings", payload);
    dirty = false;
    note.textContent = result.restart_required?.length
      ? `${result.message}（重启学习工作台后生效）`
      : "已保存。文本/视觉模型下一轮对话立即生效。";
    toast(result.message || "已保存", "ok");
    document.getElementById("agent-token").value = "";
    document.getElementById("vision-key").value = "";
    current = await api.get("/api/settings");
    fill(current);
    note.textContent = result.restart_required?.length
      ? `${result.message}（重启学习工作台后生效）`
      : "已保存";
    loadLocalIndex();
    window.dispatchEvent(new CustomEvent("learnsys:prefs", { detail: payload.modules }));
  } catch (error) {
    note.textContent = "";
    toast(error.message || "保存失败", "err");
  } finally {
    buttons.forEach((button) => { if (button) button.disabled = false; });
  }
}

async function test(kind) {
  const button = document.getElementById(kind === "vision" ? "test-vision" : "test-text");
  const result = document.getElementById(kind === "vision" ? "test-vision-result" : "test-text-result");
  if (dirty) {
    toast("先保存再测：测试用的是已保存的配置");
    return;
  }
  button.disabled = true;
  result.className = "test-result";
  result.textContent = "测试中…";
  try {
    const answer = await api.post("/api/settings/test", { kind });
    result.textContent = answer.message || (answer.ok ? "可用" : "不可用");
    result.className = `test-result ${answer.ok ? "ok" : "err"}`;
  } catch (error) {
    result.textContent = error.message || "测试失败";
    result.className = "test-result err";
  } finally {
    button.disabled = false;
  }
}

async function backup() {
  const button = document.getElementById("backup-now");
  const result = document.getElementById("backup-result");
  button.disabled = true;
  result.className = "test-result";
  result.textContent = "备份中…";
  try {
    const answer = await api.post("/api/settings/backup", {});
    result.textContent = answer.message || "备份完成";
    result.className = "test-result ok";
    if (answer.path) document.getElementById("backup-dir").textContent = `最近备份：${answer.path}`;
  } catch (error) {
    result.textContent = error.message || "备份失败";
    result.className = "test-result err";
  } finally {
    button.disabled = false;
  }
}
