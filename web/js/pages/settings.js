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
}

function fill(data) {
  setValue("agent-base", data.agent?.base_url);
  setValue("agent-model", data.agent?.model);
  setValue("agent-fast", data.agent?.fast_model);
  setValue("agent-tokens", data.agent?.max_tokens);
  document.getElementById("agent-thinking").checked = !!data.agent?.thinking;
  document.getElementById("agent-token").value = "";
  document.getElementById("agent-token-hint").textContent = keyHint(
    data.agent?.auth_token_set, data.agent?.auth_token_mask, data.agent?.auth_token_source);

  setValue("vision-base", data.vision?.base_url);
  setValue("vision-model", data.vision?.model);
  document.getElementById("vision-key").value = "";
  document.getElementById("vision-key-hint").textContent = keyHint(
    data.vision?.api_key_set, data.vision?.api_key_mask, data.vision?.api_key_source);

  setValue("hotkey", data.hotkey || "");
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
}

function collect() {
  const agent = {
    base_url: valueOf("agent-base"),
    model: valueOf("agent-model"),
    fast_model: valueOf("agent-fast"),
    thinking: document.getElementById("agent-thinking").checked,
  };
  const tokens = Number(valueOf("agent-tokens"));
  if (Number.isFinite(tokens) && tokens > 0) agent.max_tokens = Math.round(tokens);
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

  return { agent, vision, hotkey: valueOf("hotkey"), modules };
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
      ? `${result.message}（重启问一问后生效）`
      : "已保存。文本/视觉模型下一轮对话立即生效。";
    toast(result.message || "已保存", "ok");
    document.getElementById("agent-token").value = "";
    document.getElementById("vision-key").value = "";
    current = await api.get("/api/settings");
    fill(current);
    note.textContent = result.restart_required?.length
      ? `${result.message}（重启问一问后生效）`
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
