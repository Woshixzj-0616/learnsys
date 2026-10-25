// 录像详情里的「问一问」：同一个 Agent / 同一套对话表，只是宿主是录像页。
// 对话落 conversations（module=ask、origin=video、recording_id），问一问侧栏也会看到。
import { api, streamChat } from "../../api.js";
import { renderInto } from "../../markdown.js";
import { escapeHtml, toast } from "../../ui.js";
import { dateText } from "./format.js";

export function createAIPanel({ detailBody }) {
  let controller = null;
  let seq = 0;
  let recordingId = 0;
  let conversationId = 0;
  let messages = [];
  let historyItems = [];
  let epoch = 0;

  const q = (selector) => detailBody.querySelector(selector);

  function setOpenLink() {
    const link = q("#rec-ai-open");
    if (!link) return;
    link.onclick = () => {
      location.hash = conversationId
        ? `#/ask/${conversationId}`
        : `#/ask?recording=${recordingId}`;
    };
  }

  function messageText(message) {
    const content = message?.content;
    if (typeof content === "string") return content;
    if (content && typeof content === "object") {
      return String(content.text || content.answer || "");
    }
    return "";
  }

  function scrollThread() {
    const thread = q("#rec-ai-thread");
    if (thread) thread.scrollTop = thread.scrollHeight;
  }

  function renderThread() {
    const thread = q("#rec-ai-thread");
    if (!thread) return;
    if (!messages.length) {
      thread.hidden = true;
      thread.innerHTML = "";
      return;
    }
    thread.hidden = false;
    thread.innerHTML = messages.map((message) => {
      const role = message.role === "assistant" ? "assistant" : "user";
      const text = messageText(message);
      return `<div class="rec-ai-msg ${role}">
        <div class="rec-ai-bubble${role === "assistant" ? " rec-analysis-body" : ""}">${
          role === "user" ? escapeHtml(text) : ""}</div>
      </div>`;
    }).join("");
    const bubbles = [...thread.querySelectorAll(".rec-ai-msg.assistant .rec-ai-bubble")];
    messages.filter((message) => message.role === "assistant")
      .forEach((message, index) => {
        const bubble = bubbles[index];
        if (bubble) renderInto(bubble, messageText(message) || "（没有回答）");
      });
    scrollThread();
  }

  function renderHistory() {
    const box = q("#rec-ai-history");
    if (!box) return;
    if (!historyItems.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = `<div class="rec-ai-history-label">这段录像的对话</div>${
      historyItems.slice(0, 8).map((item) => `
        <button class="rec-ai-conv${item.id === conversationId ? " active" : ""}"
            type="button" data-ai-conv="${item.id}">
          <span>${escapeHtml(item.title || "新对话")}</span>
          <small>${escapeHtml(dateText(item.updated_at))}</small>
        </button>`).join("")}`;
    box.querySelectorAll("[data-ai-conv]").forEach((button) => {
      button.addEventListener("click", () => openConversation(Number(button.dataset.aiConv)));
    });
  }

  async function loadHistory({ autoOpen = false } = {}) {
    if (!recordingId) return;
    const myEpoch = epoch;
    try {
      const data = await api.get(
        `/api/conversations?origin=video&recording_id=${recordingId}&limit=20`);
      if (myEpoch !== epoch) return;
      historyItems = Array.isArray(data.items) ? data.items : [];
      renderHistory();
      if (autoOpen && !controller && historyItems.length) {
        await openConversation(historyItems[0].id);
      }
    } catch (error) {
      historyItems = [];
      renderHistory();
    }
  }

  async function openConversation(id) {
    if (!id || controller) return;
    const myEpoch = epoch;
    try {
      const data = await api.get(`/api/conversations/${id}`);
      if (myEpoch !== epoch) return;
      conversationId = Number(data.id || 0);
      messages = Array.isArray(data.messages) ? data.messages : [];
      renderThread();
      renderHistory();
      setOpenLink();
    } catch (error) {
      toast(error.message || "对话没打开");
    }
  }

  function appendStreaming(question) {
    const thread = q("#rec-ai-thread");
    if (!thread) return null;
    thread.hidden = false;
    thread.insertAdjacentHTML("beforeend", `
      <div class="rec-ai-msg user"><div class="rec-ai-bubble">${escapeHtml(question)}</div></div>
      <div class="rec-ai-msg assistant"><div class="rec-ai-bubble rec-ai-stream">思考中…</div></div>`);
    scrollThread();
    // 取**最后一条**助手气泡 —— 上一问完成后如果还留着 rec-ai-stream 类，
    // querySelector 会拿到上一条，第二问的流就会写进第一问的答案里（真机 bug）。
    const bubbles = thread.querySelectorAll(".rec-ai-msg.assistant .rec-ai-bubble");
    return bubbles.length ? bubbles[bubbles.length - 1] : null;
  }

  async function ask() {
    if (controller) {
      toast("上一问还在写，等它写完再问");
      return;
    }
    const input = q("#rec-ai-input");
    const send = q("#rec-ai-send");
    const stopBtn = q("#rec-ai-stop");
    if (!input || !recordingId) return;
    const question = input.value.trim();
    if (!question) {
      input.focus();
      toast("先写一个问题");
      return;
    }
    const bubble = appendStreaming(question);
    if (!bubble) return;
    input.value = "";
    if (send) send.disabled = true;
    if (stopBtn) stopBtn.hidden = false;
    const currentSeq = ++seq;
    controller = new AbortController();
    let acc = "";
    try {
      await streamChat({
        message: question,
        conversation_id: conversationId || null,
        recording_id: recordingId,
        surface: "video",
        module: "ask",
        mode: "explain",
      }, (event) => {
        if (currentSeq !== seq) return;
        if (event.kind === "start") {
          conversationId = Number(event.data?.conversation_id || 0);
          setOpenLink();
          loadHistory();
        } else if (event.kind === "thinking") {
          if (!acc) bubble.textContent = "思考中…";
        } else if (event.kind === "text") {
          acc += event.text || "";
          bubble.textContent = acc;
          scrollThread();
        } else if (event.kind === "done") {
          const final = String(event.data?.text || acc || "");
          bubble.classList.remove("rec-ai-stream");
          if (final) renderInto(bubble, final);
          else bubble.textContent = "模型没有回答";
          loadHistory();
        } else if (event.kind === "error") {
          bubble.classList.remove("rec-ai-stream");
          bubble.textContent = event.text || "模型没有回答";
        }
      }, controller.signal);
      if (currentSeq === seq && acc && bubble.textContent === acc) {
        renderInto(bubble, acc);
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        bubble.textContent = error.message || "模型没有回答";
      }
    } finally {
      if (currentSeq === seq) {
        bubble.classList.remove("rec-ai-stream");
        if (send) send.disabled = false;
        if (stopBtn) stopBtn.hidden = true;
      }
      controller = null;
    }
  }

  function stop() {
    controller?.abort();
    controller = null;
    seq += 1;
    detailBody.querySelectorAll(".rec-ai-stream")
      .forEach((node) => node.classList.remove("rec-ai-stream"));
    const send = q("#rec-ai-send");
    const stopBtn = q("#rec-ai-stop");
    if (send) send.disabled = false;
    if (stopBtn) stopBtn.hidden = true;
  }

  function newThread() {
    if (controller) return;
    conversationId = 0;
    messages = [];
    renderThread();
    renderHistory();
    setOpenLink();
    q("#rec-ai-input")?.focus();
  }

  function bind() {
    const send = q("#rec-ai-send");
    const stopBtn = q("#rec-ai-stop");
    const input = q("#rec-ai-input");
    if (send) send.onclick = ask;
    if (stopBtn) stopBtn.onclick = stop;
    const newBtn = q("#rec-ai-new");
    if (newBtn) newBtn.onclick = newThread;
    if (input) {
      input.onkeydown = (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          ask();
        }
      };
    }
    setOpenLink();
  }

  function reset(nextRecordingId) {
    stop();
    epoch += 1;
    recordingId = Number(nextRecordingId || 0);
    conversationId = 0;
    messages = [];
    historyItems = [];
    const thread = q("#rec-ai-thread");
    if (thread) {
      thread.hidden = true;
      thread.innerHTML = "";
    }
    const input = q("#rec-ai-input");
    if (input) input.value = "";
    bind();
    loadHistory({ autoOpen: true });
  }

  function focus() {
    const panel = q("#rec-ai");
    panel?.scrollIntoView({ behavior: "smooth", block: "center" });
    q("#rec-ai-input")?.focus();
  }

  function dispose() {
    stop();
    epoch += 1;
    recordingId = 0;
    conversationId = 0;
    messages = [];
    historyItems = [];
  }

  return { reset, ask, stop, focus, dispose };
}
