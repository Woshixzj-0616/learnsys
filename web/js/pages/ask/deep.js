// 深度分析：显式触发外部 Claude / 本地 CLI，不混进主对话。
import { api } from "../../api.js";
import { renderInto } from "../../markdown.js";
import { toast } from "../../ui.js";
import { dom, state } from "./state.js";
import { addUserBlock, createAssistantBlock, scrollBottom } from "./thread.js";

export async function loadDeepStatus() {
  const button = dom.deepRun;
  if (!button) return;
  try {
    const info = await api.get("/api/agent/deep");
    button.hidden = !info.available;
    if (info.available) {
      button.title = info.model
        ? `深度分析（${info.model}，${info.provider === "command" ? "本地命令" : "API"}）`
        : "深度分析";
    }
  } catch {
    button.hidden = true;
  }
}

export async function runDeepAnalysis() {
  const button = dom.deepRun;
  const prompt = dom.input.value.trim();
  if (!prompt) {
    toast("先把要深度分析的问题写在输入框里");
    dom.input.focus();
    return;
  }
  if (state.streaming) {
    toast("先等这一轮写完再做深度分析");
    return;
  }
  const context = state.material
    ? `资料：${state.material.title}（${state.material.chars} 字）`
    : "";
  addUserBlock(`［深度分析］${prompt}`);
  const block = createAssistantBlock();
  block.status.hidden = false;
  block.status.innerHTML = '<span class="pulse"></span><span>深度分析中，可能要几十秒…</span>';
  button.disabled = true;
  scrollBottom(true);
  try {
    const result = await api.post("/api/agent/deep", { prompt, context });
    block.status.hidden = true;
    block.body.hidden = false;
    renderInto(block.body, result.text || "");
    block.sources.textContent =
      `深度分析 · ${result.provider === "command" ? "本地命令" : "API"}`
      + (result.model ? ` · ${result.model}` : "")
      + (result.ms ? ` · ${(result.ms / 1000).toFixed(1)} 秒` : "");
  } catch (error) {
    block.status.hidden = true;
    block.error.hidden = false;
    block.error.textContent = error.message || "深度分析失败";
  } finally {
    button.disabled = false;
    scrollBottom(true);
  }
}
