// 派活表单：agent / 工作目录 / 挂资料 / 提示词。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";

export function createCompose({ root, onStart }) {
  const agent = root.querySelector("#ag-agent");
  const workspace = root.querySelector("#ag-workspace");
  const roots = root.querySelector("#ag-roots");
  const material = root.querySelector("#ag-material");
  const prompt = root.querySelector("#ag-prompt");
  const timeout = root.querySelector("#ag-timeout");
  const start = root.querySelector("#ag-start");
  const note = root.querySelector("#ag-note");
  let meta = { agents: [], allowed_roots: [], default_workspace: "", timeout: 300 };
  let busy = false;

  function renderAgents() {
    agent.innerHTML = meta.agents.map((item) => {
      const label = `${item.name}${item.version ? ` · ${item.version}` : ""}`
        + (item.available ? "" : `（${item.note || "不可用"}）`);
      return `<option value="${escapeHtml(item.id)}"${item.available ? "" : " disabled"}>`
        + `${escapeHtml(label)}</option>`;
    }).join("");
    const firstAvailable = meta.agents.find((item) => item.available);
    if (firstAvailable) agent.value = firstAvailable.id;
    const available = meta.agents.filter((item) => item.available).length;
    note.textContent = available
      ? "只读：agent 不能改文件、不能跑命令"
      : "本机没有可用的 agent；先安装 Claude Code 或打开 Codex";
    start.disabled = !available || busy;
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

  async function load(nextMeta) {
    meta = nextMeta || meta;
    renderAgents();
    renderRoots();
    await renderMaterials();
  }

  function payload() {
    return {
      agent: agent.value,
      workspace: workspace.value.trim(),
      material_id: Number(material.value) || 0,
      timeout: Number(timeout.value) || 0,
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
    } finally {
      busy = false;
      start.textContent = "开始任务";
      start.disabled = !meta.agents.some((item) => item.available);
    }
  }

  start.addEventListener("click", submit);
  prompt.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  });

  return { load, submit };
}
