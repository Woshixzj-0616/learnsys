// 设置页：读掩码配置、保存、测连接、备份、模块开关。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

let ctxRef = null;
let current = null;
let dirty = false;

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
  loadMemories();
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
  document.getElementById("data-root").value = data.data_root || "";
  document.getElementById("settings-path").textContent = `设置在：${data.settings_path || ""}`;
  document.getElementById("backup-dir").textContent = `备份目录：${data.backup_dir || ""}`;

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

  document.getElementById("memory-add").addEventListener("click", addMemory);
  const input = document.getElementById("memory-input");
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addMemory();
    }
  });
  document.getElementById("memory-list").addEventListener("click", onMemoryAction);
  document.getElementById("memory-list").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.target.matches(".memory-text")) return;
    event.preventDefault();          // 别让回车顺手提交整页设置
    event.target.closest(".memory-row")?.querySelector("[data-act='save']")?.click();
  });
}

async function loadMemories() {
  const list = document.getElementById("memory-list");
  if (!list) return;
  try {
    const data = await api.get("/api/memory");
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      list.innerHTML = '<div class="hint">还没有记忆。Agent 听到「以后都…」会自动记；也可以在上面手动加。</div>';
      return;
    }
    list.innerHTML = items.map((item) => `
      <div class="memory-row" data-id="${item.id}">
        <input class="input memory-text" value="${escapeHtml(item.content)}" maxlength="500">
        <button class="btn btn-quiet" type="button" data-act="save">保存</button>
        <button class="btn btn-quiet" type="button" data-act="del">删除</button>
      </div>`).join("");
  } catch (error) {
    list.innerHTML = `<div class="empty">记忆没读出来：${escapeHtml(error.message || error)}</div>`;
  }
}

async function addMemory() {
  const input = document.getElementById("memory-input");
  const content = input.value.trim();
  if (!content) return;
  try {
    const result = await api.post("/api/memory", { content });
    input.value = "";
    toast(result.message || "已记住", "ok");
    await loadMemories();
  } catch (error) {
    toast(error.message || "没记住", "err");
  }
}

async function onMemoryAction(event) {
  const button = event.target.closest("button[data-act]");
  if (!button) return;
  const row = button.closest(".memory-row");
  const id = Number(row?.dataset.id || 0);
  if (!id) return;
  if (button.dataset.act === "del") {
    try {
      const result = await api.del(`/api/memory/${id}`);
      toast(result.message || "已忘掉", "ok");
      await loadMemories();
    } catch (error) {
      toast(error.message || "删除失败", "err");
    }
    return;
  }
  const content = row.querySelector(".memory-text")?.value.trim() || "";
  if (!content) return;
  try {
    const result = await api.post(`/api/memory/${id}`, { content });
    toast(result.message || "已更新", "ok");
    await loadMemories();
  } catch (error) {
    toast(error.message || "更新失败", "err");
  }
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

  return {
    agent, vision, hotkey: valueOf("hotkey"), modules,
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
