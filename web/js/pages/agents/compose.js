// 派活表单：agent / 工作目录 / 挂资料 / 提示词。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";
import { agentName, promptPreview, statusText } from "./format.js";

export function createCompose({ root, onStart }) {
  const agent = root.querySelector("#ag-agent");
  const workspace = root.querySelector("#ag-workspace");
  const roots = root.querySelector("#ag-roots");
  const material = root.querySelector("#ag-material");
  const parent = root.querySelector("#ag-parent");
  const prompt = root.querySelector("#ag-prompt");
  const mode = root.querySelector("#ag-mode");
  const timeout = root.querySelector("#ag-timeout");
  const start = root.querySelector("#ag-start");
  const note = root.querySelector("#ag-note");
  const hint = root.querySelector("#ag-hint");
  let meta = { agents: [], allowed_roots: [], default_workspace: "", timeout: 300 };
  let tasks = [];
  let busy = false;

  function canContinue(task) {
    if (!task) return false;
    if (task.status === "failed" || task.status === "cancelled") return false;
    if (task.status === "done" && !task.has_result) return false;
    return true;
  }

  function renderParents() {
    const current = parent.value;
    const options = tasks.filter(canContinue);
    parent.innerHTML = '<option value="0">不接续（独立任务）</option>'
      + options.map((task) => {
        const label = `#${task.id} · ${agentName(task.agent, meta.agents)}`
          + ` · ${statusText(task.status)} · ${promptPreview(task.prompt, 36)}`;
        return `<option value="${task.id}">${escapeHtml(label)}</option>`;
      }).join("");
    parent.value = options.some((task) => String(task.id) === current) ? current : "0";
  }

  function renderNote() {
    const write = mode.value === "write";
    const isCodex = agent.value === "codex";
    const available = meta.agents.some((item) => item.available);
    let text = "只读：agent 不能改文件、不能跑命令";
    if (write && isCodex) {
      text = "可写：Codex 只在所选目录内写，整任务授权，不逐条确认";
    } else if (write) {
      text = "可写：每次改文件 / 跑命令都会停下来等你确认";
    }
    if (Number(parent.value)) {
      text += write
        ? "；上一步输出会作为资料注入，请确认来源可信"
        : "；上一步输出会作为资料注入";
    }
    note.textContent = text;
    hint.textContent = text;
    start.disabled = !available || busy;
  }

  function renderAgents() {
    agent.innerHTML = meta.agents.map((item) => {
      const label = `${item.name}${item.version ? ` · ${item.version}` : ""}`
        + (item.available ? "" : `（${item.note || "不可用"}）`);
      return `<option value="${escapeHtml(item.id)}"${item.available ? "" : " disabled"}>`
        + `${escapeHtml(label)}</option>`;
    }).join("");
    const firstAvailable = meta.agents.find((item) => item.available);
    if (firstAvailable) agent.value = firstAvailable.id;
    if (!meta.agents.some((item) => item.available)) {
      note.textContent = "本机没有可用的 agent；先安装 Claude Code 或打开 Codex";
      hint.textContent = note.textContent;
      start.disabled = true;
      return;
    }
    renderNote();
  }

  function renderRoots() {
    roots.innerHTML = meta.allowed_roots
      .map((path) => `<option value="${escapeHtml(path)}"></option>`).join("");
    workspace.placeholder = `留空 = ${meta.default_workspace || "数据目录"}`;
    if (!workspace.value && meta.default_workspace) {
      workspace.value = meta.default_workspace;
    }
    timeout.value = String(meta.timeout || 300);
  }

  async function renderMaterials() {
    try {
      const data = await api.get("/api/materials?limit=100");
      const items = data?.items || [];
      material.innerHTML = '<option value="">不挂资料</option>'
        + items.map((item) => `<option value="${item.id}">`
          + `#${item.id} ${escapeHtml(item.title || "未命名")}</option>`).join("");
    } catch {
      material.innerHTML = '<option value="">不挂资料</option>';
    }
  }

  async function load(nextMeta, nextTasks) {
    meta = nextMeta || meta;
    if (nextTasks) tasks = nextTasks;
    renderAgents();
    renderRoots();
    renderParents();
    await renderMaterials();
  }

  function setTasks(items) {
    tasks = Array.isArray(items) ? items : [];
    renderParents();
    renderNote();
  }

  function setParent(taskId) {
    const value = String(Number(taskId) || 0);
    if (![...parent.options].some((item) => item.value === value)) return false;
    parent.value = value;
    renderNote();
    return true;
  }

  function payload() {
    return {
      agent: agent.value,
      workspace: workspace.value.trim(),
      material_id: Number(material.value) || 0,
      mode: mode.value === "write" ? "write" : "read",
      timeout: Number(timeout.value) || 0,
      depends_on: Number(parent.value) || 0,
      prompt: prompt.value.trim(),
    };
  }

  async function submit() {
    if (busy) return;
    const body = payload();
    if (!body.agent) return toast("先选一个 agent");
    if (!body.prompt) {
      prompt.focus();
      return toast("先写任务内容");
    }
    busy = true;
    start.disabled = true;
    start.textContent = "启动中…";
    try {
      await onStart(body);
      prompt.value = "";
      parent.value = "0";
    } finally {
      busy = false;
      start.textContent = "开始任务";
      renderNote();
    }
  }

  start.addEventListener("click", submit);
  agent.addEventListener("change", renderNote);
  mode.addEventListener("change", renderNote);
  parent.addEventListener("change", renderNote);
  prompt.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  });

  return { load, setTasks, setParent, submit };
}
