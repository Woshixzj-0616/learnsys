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

/** 写操作确认：原生确认框 → 告诉后台允许/拒绝。四个页面共用这一处。 */
function askWriteConfirm(data) {
  const summary = String(data.summary || "这次写入");
  const allowed = window.confirm(`${summary}\n\n允许这次写入吗？`);
  api.post("/api/agent/confirm", {
    run_id: data.run_id || "",
    request_id: data.request_id || "",
    approve: allowed,
  }).catch((error) => {
    console.warn("写入确认没有送到后台（可能已超时）", error);
  });
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

export function stopChat(conversationId) {
  return api.post("/api/agent/stop", { conversation_id: conversationId ?? null });
}
