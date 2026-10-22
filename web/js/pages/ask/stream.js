// SSE 流式：开始、逐事件渲染、完成/出错/停止。
import { streamChat, stopChat } from "../../api.js";
import { state, dom, TOOL_NAMES } from "./state.js";
import { addSource, addToolRow, attachReplay, createAssistantBlock,
         paintAssistant, renderPlan, setAssistantStatus, showCheck,
         updateToolPreview } from "./thread.js";
import { loadConversations } from "./conversations.js";
import { updateSendButton } from "./attachments.js";


export async function startStreaming(payload) {
  state.streaming = true;
  state.stopped = false;
  state.text = "";
  state.thinking = "";
  state.runId = "";
  state.usedTools = new Set();
  state.usedVision = false;
  state.thinkingDirty = false;
  state.startedAt = Date.now();
  state.assistant = createAssistantBlock();
  setAssistantStatus(state.assistant, "思考中", true);
  dom.input.disabled = true;
  dom.send.hidden = true;
  dom.stop.hidden = false;
  dom.mode.disabled = true;
  updateSendButton();

  state.timer = setInterval(() => {
    if (!state.assistant) return;
    const seconds = Math.max(1, Math.round((Date.now() - state.startedAt) / 1000));
    const label = state.text ? "正在写" : "思考中";
    setAssistantStatus(state.assistant, `${label} · ${seconds} 秒`, true);
  }, 1000);

  state.controller = new AbortController();
  let paintTimer = 0;
  const schedulePaint = () => {
    if (paintTimer) return;
    paintTimer = setTimeout(() => {
      paintTimer = 0;
      paintAssistant();
    }, 110);
  };

  try {
    await streamChat(payload, (event) => {
      const block = state.assistant;
      if (!block) return;
      if (event.kind === "start") {
        const id = Number(event.data?.conversation_id || 0);
        state.runId = String(event.data?.run_id || "");
        if (id && state.convId !== id) {
          state.convId = id;
          history.replaceState(null, "", `#/ask/${id}`);
        }
      } else if (event.kind === "plan") {
        renderPlan(block, event.data?.steps || [], !!event.data?.truncated);
        setAssistantStatus(block, "按计划执行", true);
      } else if (event.kind === "plan_update") {
        renderPlan(block, event.data?.steps || []);
      } else if (event.kind === "check") {
        showCheck(block, event.data || {});
      } else if (event.kind === "rewrite") {
        state.text = String(event.data?.text || "");
        block.body.hidden = !state.text;
        paintAssistant(true);
        setAssistantStatus(block, "自检后已重写", true);
      } else if (event.kind === "thinking") {
        state.thinking += event.text || "";
        state.thinkingDirty = true;
        if (block.thinkingEl.hidden) {
          block.thinkingEl.hidden = false;
          block.thinkingEl.open = true;     // 先展开：让人看到推理在推进
        }
        setAssistantStatus(block, "思考中", true);
        schedulePaint();
      } else if (event.kind === "activity") {
        if (event.text) setAssistantStatus(block, event.text, true);
      } else if (event.kind === "text") {
        const firstText = !state.text;
        state.text += event.text || "";
        if (firstText && state.thinking) {
          block.thinkingEl.open = false;    // 正文开始：思考收起成一行，不挤占答案
        }
        setAssistantStatus(block, state.text ? "正在写" : "思考中", true);
        schedulePaint();
      } else if (event.kind === "tool_start") {
        addToolRow(block, event.data?.name || "tool", event.data?.input || {},
          event.data?.goal || "", event.data?.step);
        setAssistantStatus(block, event.data?.goal || "在查本地记录", true);
      } else if (event.kind === "tool_end") {
        updateToolPreview(block, event.data?.name || "", event.data?.preview || "",
          event.data?.ok !== false, event.data?.step);
        if (event.data?.ok === false) {
          setAssistantStatus(block, "这步没成功，正在换路", true);
        }
      } else if (event.kind === "vision") {
        if (typeof event.data?.used_vision === "boolean") {
          state.usedVision = event.data.used_vision;
        } else {
          setAssistantStatus(block, "正在看图", true);
        }
      } else if (event.kind === "done") {
        const finalText = String(event.data?.text || state.text || "");
        if (finalText) state.text = finalText;
        if (event.data?.thinking) {
          state.thinking = String(event.data.thinking);
          state.thinkingDirty = true;
        }
        paintAssistant(true);
        if (event.data?.truncated) {
          setAssistantStatus(block, "回答达到上限，末尾可能被截断");
        }
        finishStreaming(block, true);
      } else if (event.kind === "error") {
        showStreamError(block, event.text || "模型没有回答");
      }
    }, state.controller.signal);
    if (state.streaming) finishStreaming(state.assistant, true);
  } catch (error) {
    if (error?.name === "AbortError") {
      finishStreaming(state.assistant, false, "已停止，答案保留到中断处");
    } else {
      showStreamError(state.assistant, error?.message || "连接中断了");
    }
  } finally {
    clearTimeout(paintTimer);
  }
}

export function finishStreaming(block, ok, note = "") {
  if (!state.streaming) return;
  state.streaming = false;
  clearInterval(state.timer);
  state.timer = 0;
  dom.input.disabled = false;
  dom.send.hidden = false;
  dom.stop.hidden = true;
  dom.mode.disabled = false;
  updateSendButton();

  if (!block) return;
  const seconds = Math.max(1, Math.round((Date.now() - state.startedAt) / 1000));

  if (ok) {
    if (state.text) paintAssistant(true);
    setAssistantStatus(block, `用了 ${seconds} 秒`);
    for (const name of state.usedTools) addSource(block, TOOL_NAMES[name] || name);
    if (state.usedVision) addSource(block, "视觉模型");
    if (state.text) {
      state.messages.push({ role: "assistant", content: {
        text: state.text, thinking: state.thinking, run_id: state.runId || undefined } });
    }
    if (state.runId) attachReplay(block, state.runId);
  } else {
    setAssistantStatus(block, note || "已停止");
    if (state.text) {
      paintAssistant(true);
      state.messages.push({ role: "assistant", content: {
        text: state.text, thinking: state.thinking, run_id: state.runId || undefined } });
    }
  }

  if (state.convId) loadConversations();
  dom.input.focus();
}

export function showStreamError(block, message) {
  state.streaming = false;
  clearInterval(state.timer);
  state.timer = 0;
  dom.input.disabled = false;
  dom.send.hidden = false;
  dom.stop.hidden = true;
  dom.mode.disabled = false;
  updateSendButton();
  if (block) {
    block.error.hidden = false;
    block.error.textContent = String(message || "出错了");
    setAssistantStatus(block, "出错了");
    if (state.text) paintAssistant(true);
  }
  if (state.convId) loadConversations();
}

export async function stopStreaming() {
  if (!state.streaming) return;
  state.stopped = true;
  dom.status.textContent = "正在停止…";
  state.controller?.abort();
  try {
    await stopChat(state.convId);
  } catch {
    // 已经断了就不用再报
  }
  dom.status.textContent = "";
}
