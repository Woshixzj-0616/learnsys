// 本地服务封装：令牌、JSON、SSE、中文错误。
// 只跟 127.0.0.1:8765 说话；令牌从 /api/health 拿，恶意网页读不到（Origin 拦截）。

let TOKEN = "";
let HEALTH = null;

export async function initApi() {
  const response = await fetch("/api/health", { cache: "no-store" });
  if (!response.ok) throw new Error(`后台没有响应（${response.status}）`);
  HEALTH = await response.json();
  TOKEN = HEALTH.token || "";
  return HEALTH;
}

export function health() {
  return HEALTH || {};
}

function headers(extra = {}) {
  return {
    "Content-Type": "application/json",
    "X-Learnsys-Token": TOKEN,
    ...extra,
  };
}

async function parseError(response) {
  let detail = "";
  try {
    const data = await response.json();
    detail = typeof data?.detail === "string" ? data.detail : "";
  } catch {
    // 不是 JSON，就用状态码说话
  }
  if (response.status === 403) return "本地令牌不对，刷新页面再试";
  return detail || `请求失败（${response.status}）`;
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: headers(options.headers) });
  if (!response.ok) throw new Error(await parseError(response));
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  patch: (path, body) => request(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  del: (path) => request(path, { method: "DELETE" }),
};

/** 资料上传：直接把 File 当 body 发（不 base64），参数走 query。 */
export async function uploadRaw(path, file) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream", "X-Learnsys-Token": TOKEN },
    body: file,
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

/** 带令牌下载文件（GET），成功后触发浏览器保存。 */
export async function download(path, filename) {
  const response = await fetch(path, { headers: headers() });
  if (!response.ok) throw new Error(await parseError(response));
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename || "下载.csv";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** 文件 → base64 → /api/upload。图片返回 path，文档返回抽取的 text。 */
export async function upload(file) {
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("文件读不出来"));
    reader.readAsDataURL(file);
  });
  const lower = (file.name || "").toLowerCase();
  const image = /\.(png|jpe?g|webp|gif)$/.test(lower);
  return api.post("/api/upload", {
    name: file.name,
    data,
    kind: image ? "image" : "doc",
  });
}

/* ---- 写操作确认：非阻塞卡片，四个页面共用 ----
   之前用 window.confirm：同步阻塞整个页面，流式渲染停住，切页/关标签后确认就丢了。
   现在放在 body 上排队显示，SSE 继续收；超时按拒绝处理（后端 120 秒）。 */
const CONFIRM_SECONDS = 120;
const RUN_CODE_ALLOW_KEY = "learnsys_allow_run_code";
const confirmQueue = [];
let activeConfirm = null;
let confirmTimer = 0;

function postConfirm(data, approve) {
  return api.post("/api/agent/confirm", {
    run_id: data.run_id || "",
    request_id: data.request_id || "",
    approve: Boolean(approve),
  });
}

function confirmNotice(text) {
  let node = document.getElementById("confirm-notice");
  if (!node) {
    node = document.createElement("div");
    node.id = "confirm-notice";
    node.className = "confirm-notice";
    document.body.appendChild(node);
  }
  node.textContent = String(text || "");
  node.hidden = false;
  clearTimeout(confirmNotice.timer);
  confirmNotice.timer = setTimeout(() => { node.hidden = true; }, 3600);
}

function confirmCard() {
  let card = document.getElementById("confirm-card");
  if (card) return card;
  card = document.createElement("div");
  card.id = "confirm-card";
  card.className = "confirm-card";
  card.setAttribute("role", "group");
  card.setAttribute("aria-live", "assertive");
  card.innerHTML = `
    <div class="confirm-head">
      <span class="confirm-label"></span>
      <span class="confirm-left"></span>
    </div>
    <div class="confirm-summary"></div>
    <div class="confirm-hint"></div>
    <div class="confirm-actions">
      <button type="button" class="btn btn-primary" data-act="allow">允许一次</button>
      <button type="button" class="btn" data-act="allow-session" hidden>本页面内不再询问</button>
      <button type="button" class="btn btn-quiet" data-act="deny">拒绝</button>
    </div>
    <div class="confirm-error" hidden></div>`;
  document.body.appendChild(card);
  card.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button || !activeConfirm) return;
    const act = button.dataset.act;
    if (act === "allow-session") {
      sessionStorage.setItem(RUN_CODE_ALLOW_KEY, "1");
      confirmNotice("本页面内运行代码不再询问（刷新页面后恢复）");
      finishConfirm(true);
    } else if (act === "allow") {
      finishConfirm(true);
    } else {
      finishConfirm(false);
    }
  });
  return card;
}

function finishConfirm(approve, note = "") {
  const data = activeConfirm;
  if (!data) return;
  clearInterval(confirmTimer);
  confirmTimer = 0;
  activeConfirm = null;
  const card = document.getElementById("confirm-card");
  if (card) card.hidden = true;
  postConfirm(data, approve).catch((error) => {
    // 用户已经做了选择，但后台没收到：明确说出来，不要静默。
    confirmNotice(`确认没有送到后台：${error?.message || "可能已超时"}`);
  });
  if (note) confirmNotice(note);
  pumpConfirm();
}

function renderConfirm(data) {
  const card = confirmCard();
  card.hidden = false;
  card.querySelector(".confirm-label").textContent = String(data.label || "需要你确认");
  card.querySelector(".confirm-summary").textContent = String(data.summary || "这次操作");
  card.querySelector(".confirm-hint").textContent = data.tool === "run_code"
    ? "在临时目录运行，默认禁网、有超时，不改你的学习数据。"
    : "这一步会修改本机数据，确认后才会执行。";
  const sessionButton = card.querySelector('[data-act="allow-session"]');
  sessionButton.hidden = data.tool !== "run_code";
  const errorNode = card.querySelector(".confirm-error");
  errorNode.hidden = true;
  const left = card.querySelector(".confirm-left");
  let remaining = CONFIRM_SECONDS;
  left.textContent = `${remaining} 秒`;
  clearInterval(confirmTimer);
  confirmTimer = setInterval(() => {
    remaining -= 1;
    left.textContent = `${Math.max(0, remaining)} 秒`;
    if (remaining <= 0) {
      finishConfirm(false, "确认超时，已按拒绝处理");
    }
  }, 1000);
}

function pumpConfirm() {
  if (activeConfirm) return;
  const data = confirmQueue.shift();
  if (!data) return;
  activeConfirm = data;
  renderConfirm(data);
}

function askWriteConfirm(data) {
  if (data?.tool === "run_code" && sessionStorage.getItem(RUN_CODE_ALLOW_KEY) === "1") {
    postConfirm(data, true).catch((error) => {
      confirmNotice(`自动允许运行代码失败：${error?.message || "可能已超时"}`);
    });
    return;
  }
  confirmQueue.push(data || {});
  pumpConfirm();
}

/**
 * 发一轮对话，按 SSE 事件回调。
 * onEvent({kind, text, data})；调用方用 AbortController 停止。
 */
export async function streamChat(body, onEvent, signal) {
  const response = await fetch("/api/agent/chat", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw new Error(await parseError(response));
  if (!response.body) throw new Error("浏览器不支持流式响应");

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const dispatch = (block) => {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;
    let event;
    try {
      event = JSON.parse(data);
    } catch (error) {
      console.warn("SSE 解析失败", error, data);
      return;
    }
    // 写操作确认：所有页面共用这一处弹窗，避免某个页面悄悄写入。
    if (event.kind === "confirm") {
      askWriteConfirm(event.data || {});
      return;
    }
    try {
      onEvent(event);
    } catch (error) {
      console.warn("SSE 回调失败", error, event);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      dispatch(block);
    }
  }
  if (buffer.trim()) dispatch(buffer);
}

export function stopChat(runId, conversationId) {
  return api.post("/api/agent/stop", {
    run_id: runId || "",
    conversation_id: conversationId ?? null,
  });
}
