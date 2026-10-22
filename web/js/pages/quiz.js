// 测验：基于今日记录出 5 道题；逐题作答，流式批改。
import { api, streamChat } from "../api.js";
import { renderInto } from "../markdown.js";
import { escapeHtml, toast } from "../ui.js";

let data = null;
let convId = null;
let streaming = false;
let controller = null;
let quizEventSent = false;
let pendingQuestion = "";       // 当前正在作答的题（从「【第N题】」标记里取）
let materialInfo = null;        // 从资料出题时的资料元信息
let materialId = 0;
let nodes = {};

function resetQuizState() {
  data = null;
  convId = null;
  streaming = false;
  controller = null;
  quizEventSent = false;
  pendingQuestion = "";
  materialInfo = null;
  materialId = 0;
}

export async function mount(ctx) {
  resetQuizState();
  materialId = Number(ctx.query?.get("material") || 0);
  ctx.setSub("按今天的记录出题，逐题批改");
  ctx.setActions('<a class="btn" href="#/review">去复盘</a>');
  nodes = {
    thread: ctx.root.querySelector("#quiz-thread"),
    input: ctx.root.querySelector("#quiz-input"),
    form: ctx.root.querySelector("#quiz-form"),
    send: ctx.root.querySelector("#quiz-send"),
    stop: ctx.root.querySelector("#quiz-stop"),
    state: ctx.root.querySelector("#quiz-state"),
    start: ctx.root.querySelector("#quiz-start"),
    hint: ctx.root.querySelector("#quiz-hint"),
    stats: ctx.root.querySelector("#quiz-stats"),
    eyebrow: ctx.root.querySelector("#quiz-eyebrow"),
    title: ctx.root.querySelector("#quiz-title"),
    sub: ctx.root.querySelector("#quiz-sub"),
  };
  let hasData = false;
  if (materialId) {
    try {
      const resp = await api.get(`/api/materials/${materialId}/quiz-prompt`);
      materialInfo = resp.material;
      data = { date: String(materialInfo.updated_at || "").slice(0, 10),
               quiz_prompt: resp.prompt, stats: {}, summary_lines: [] };
      hasData = true;
      ctx.setSub(`按《${materialInfo.title}》出题，逐题批改`);
      ctx.setActions('<a class="btn" href="#/materials">返回资料</a>');
      nodes.eyebrow.textContent = "测验 · 资料";
      nodes.title.textContent = `用《${materialInfo.title}》出 5 道题。`;
      nodes.sub.textContent = "题目只从这份资料里来；一次一题，答一题、批一题。答错自动进错题本。";
      nodes.start.textContent = "从这份资料出 5 道题";
    } catch (error) {
      nodes.thread.innerHTML = `<div class="empty">读不到这份资料：${escapeHtml(error.message || error)}</div>`;
      nodes.start.disabled = true;
      return;
    }
  } else {
    try {
      data = await api.get("/api/study/today");
    } catch (error) {
      nodes.thread.innerHTML = `<div class="empty">读不到今天的记录：${escapeHtml(error.message || error)}</div>`;
      nodes.start.disabled = true;
      return;
    }
    hasData = (data.stats?.minutes || 0) > 0
      || (data.stats?.transcripts || 0) > 0
      || (data.stats?.asks || 0) > 0
      || (data.stats?.trainings || 0) > 0
      || (data.stats?.cet6 || 0) > 0
      || (data.summary_lines || []).length > 0;
  }
  renderStats(data.stats || {});
  nodes.start.disabled = !hasData;
  nodes.hint.textContent = hasData
    ? (materialId ? "题目只来自这份资料" : "题目只来自今天的记录")
    : "今天还没有可出题的素材";
  nodes.start.addEventListener("click", startQuiz);
  nodes.form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendAnswer();
  });
  nodes.input.addEventListener("input", () => {
    nodes.input.style.height = "auto";
    nodes.input.style.height = Math.min(nodes.input.scrollHeight, 160) + "px";
  });
  nodes.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendAnswer();
    }
  });
  nodes.stop.addEventListener("click", () => controller?.abort());
}

function renderStats(stats) {
  if (materialInfo) {
    const scale = `${materialInfo.chars || 0} 字`
      + (materialInfo.pages ? ` / ${materialInfo.pages} 页` : "");
    nodes.stats.innerHTML = [
      ["资料", materialInfo.title],
      ["类型", materialInfo.kind || "资料"],
      ["规模", scale],
    ].map(([label, value]) => `
      <div class="review-chip"><span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong></div>`).join("");
    return;
  }
  const items = [
    ["专注", `${Number(stats.minutes || 0).toFixed(0)} 分钟`],
    ["问答", `${stats.asks || 0} 条`],
    ["转写", `${stats.transcripts || 0} 段`],
    ["网工训练", `${stats.trainings || 0} 格`],
    ["六级断点", `${stats.cet6 || 0} 个`],
  ];
  nodes.stats.innerHTML = items.map(([label, value]) => `
    <div class="review-chip"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
}

function addUserBlock(text) {
  const block = document.createElement("div");
  block.className = "quiz-msg quiz-msg-user";
  block.textContent = text;
  nodes.thread.appendChild(block);
  scrollDown();
  return block;
}

function addAssistantBlock() {
  const block = document.createElement("div");
  block.className = "quiz-msg quiz-msg-ai";
  block.innerHTML = '<p class="hint">思考中…</p>';
  nodes.thread.appendChild(block);
  scrollDown();
  return block;
}

function scrollDown() {
  nodes.thread.scrollTop = nodes.thread.scrollHeight;
}

async function startQuiz() {
  if (streaming || !data) return;
  if (!quizEventSent) {
    quizEventSent = true;
    api.post("/api/events", {
      module: "quiz", kind: "quiz",
      title: materialInfo ? `资料测验：${materialInfo.title}` : "今日测验",
      meta: { date: data.date, material_id: materialId || null },
    }).catch(() => {});
    if (materialId) {
      api.post("/api/events", {
        module: "materials", kind: "quiz", title: materialInfo?.title || "资料",
        meta: { material_id: materialId, source: "quiz" },
      }).catch(() => {});
    }
  }
  if (!nodes.thread.querySelector(".quiz-msg")) nodes.thread.innerHTML = "";
  await runTurn(data.quiz_prompt, { note: "正在出题…" });
  nodes.state.textContent = "作答中：写答案，Enter 发送";
}

async function sendAnswer() {
  const text = String(nodes.input.value || "").trim();
  if (!text) return;
  if (!convId) {
    toast("先点「出 5 道题」，再作答", "err");
    return;
  }
  if (streaming) {
    toast("等 AI 批改完这一题", "err");
    return;
  }
  nodes.input.value = "";
  nodes.input.style.height = "auto";
  addUserBlock(text);
  await runTurn(text, {
    note: "正在批改…",
    isGrading: true,
    question: pendingQuestion,
    userAnswer: text,
  });
}

/** 从「【第N题】」标记里取最后一道题；模型没按标记写就返回空串。 */
function lastQuestion(text) {
  const pattern = /【第(\d+)题】([\s\S]*?)(?=【第\d+题】|【批改】|$)/g;
  let found = "";
  for (const match of String(text || "").matchAll(pattern)) {
    found = (match[2] || "").trim();
  }
  return found;
}

/** 批改正文：从「【批改】」到下一题之前，避免把下一题混进答案。 */
function extractGrading(text) {
  const match = String(text || "").match(/【批改】([\s\S]*?)(?=【第\d+题】|$)/);
  return match ? match[1].trim() : "";
}

function attachWrongbookAction(block, payload, autoSaved) {
  const row = document.createElement("div");
  row.className = "quiz-msg-actions";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn";
  button.disabled = Boolean(autoSaved);
  button.textContent = autoSaved ? "已自动收进错题本" : "收进错题本";
  const note = document.createElement("span");
  note.className = "hint";
  note.textContent = autoSaved ? "" : "AI 漏收时可以手动补";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const data = await api.post("/api/wrongbook", {
        source: "quiz",
        conversation_id: payload.conversation_id,
        question: payload.question,
        answer: payload.answer,
        my_answer: payload.user_answer,
        tags: "测验",
        material_id: materialId || 0,
      });
      button.textContent = "已收进错题本";
      note.textContent = data?.created ? "已收进错题本" : "这道题已经在错题本里";
      toast("错题已收进错题本", "ok");
    } catch (error) {
      button.disabled = false;
      toast(error.message || "没收到错题本里", "err");
    }
  });
  row.append(button, note);
  block.appendChild(row);
}

async function runTurn(message, options = {}) {
  const note = options.note || "";
  streaming = true;
  controller = new AbortController();
  nodes.start.disabled = true;
  nodes.send.disabled = true;
  nodes.stop.hidden = false;
  nodes.state.textContent = note || "AI 正在回答…";
  const block = addAssistantBlock();
  let text = "";
  let errorText = "";
  let autoSaved = false;
  let finished = false;
  try {
    await streamChat({
      message,
      conversation_id: convId,
      mode: "quiz",
      module: "quiz",
      internal: true,
      material_id: materialId || null,
      attach_material: false,      // 只给错题归档用，不重复塞资料正文
    }, (event) => {
      if (event.kind === "start") {
        const id = Number(event.data?.conversation_id || 0);
        if (id) convId = id;
      } else if (event.kind === "text") {
        text += event.text || "";
        renderInto(block, text);
        scrollDown();
      } else if (event.kind === "rewrite") {
        text = String(event.data?.text || text);
        renderInto(block, text);
        scrollDown();
      } else if (event.kind === "tool_start") {
        // 只动状态行：这里清空 block 会把已经流出的批改文字抹掉
        nodes.state.textContent = event.data?.name === "save_wrongbook"
          ? "正在收进错题本…" : "在查本地记录…";
      } else if (event.kind === "tool_end") {
        if (event.data?.name === "save_wrongbook") {
          autoSaved = /收进错题本|已在错题本/.test(String(event.data?.preview || ""));
          nodes.state.textContent = autoSaved
            ? "已自动收进错题本" : "自动收录没成功，可以手动补收";
        }
      } else if (event.kind === "done") {
        const finalText = String(event.data?.text || text || "");
        if (finalText) {
          text = finalText;
          renderInto(block, text);
        }
        finished = true;
      } else if (event.kind === "error") {
        errorText = event.text || "模型没有回答";
      }
    }, controller.signal);
    if (errorText) throw new Error(errorText);
    if (!text.trim()) throw new Error("模型没有返回内容");
    const next = lastQuestion(text);
    if (options.isGrading && options.question) {
      const analysis = extractGrading(text) || text;
      attachWrongbookAction(block, {
        conversation_id: convId,
        question: options.question,
        user_answer: options.userAnswer || "",
        answer: analysis,
      }, autoSaved);
    }
    if (next) pendingQuestion = next;
    else if (finished) pendingQuestion = "";
  } catch (error) {
    if (error?.name === "AbortError") {
      block.innerHTML = `<p class="review-error">已停止，内容保留到中断处。</p>`;
    } else {
      block.innerHTML = `<p class="review-error">${escapeHtml(error.message || error)}</p>`;
      nodes.state.textContent = "出错了 —— 确认模型已配置、后台在运行后重试。";
    }
  } finally {
    streaming = false;
    controller = null;
    nodes.start.disabled = false;
    nodes.send.disabled = false;
    nodes.stop.hidden = true;
    nodes.state.textContent = convId ? "作答中：写答案，Enter 发送" : "还没开始";
    scrollDown();
  }
}
