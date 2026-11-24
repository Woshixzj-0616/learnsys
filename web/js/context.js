// 结构化上下文快照：九键白名单与形状归一。
// 截断与 20KB 上限**只在后端** `learnsys/context.py` 判定（唯一真相）；
// 前端不再维护一份 MAX_* 常量，改上限只改后端一处。

const KEYS = [
  "surface", "object_type", "object_id", "title", "selection",
  "surrounding", "learning_state", "recent_actions", "provenance",
];

function text(value) {
  return String(value ?? "");
}

function shortDict(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof key !== "string") continue;
    if (typeof item === "string") out[key] = text(item);
    else if (typeof item === "number" || typeof item === "boolean" || item === null) out[key] = item;
    else if (Array.isArray(item)) out[key] = item.map((x) => text(x));
    else if (item && typeof item === "object") {
      const inner = {};
      for (const [k, v] of Object.entries(item)) {
        if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
          inner[String(k)] = text(v);
        }
      }
      out[key] = inner;
    }
  }
  return out;
}

function action(value) {
  if (typeof value === "string") return text(value);
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const out = {};
    for (const [key, item] of Object.entries(value)) {
      if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
        out[String(key)] = text(item);
      }
    }
    return out;
  }
  return null;
}

/** 按九键白名单构造快照；未知键丢弃，截断与上限由后端执行。 */
export function buildSnapshot(fields = {}) {
  if (!fields || typeof fields !== "object" || Array.isArray(fields)) {
    throw new Error("上下文必须是对象");
  }
  const recent = [];
  for (const item of (Array.isArray(fields.recent_actions) ? fields.recent_actions : [])) {
    const one = action(item);
    if (one !== null) recent.push(one);
  }
  const snapshot = {
    surface: text(fields.surface),
    object_type: text(fields.object_type),
    object_id: text(fields.object_id),
    title: text(fields.title),
    selection: text(fields.selection),
    surrounding: shortDict(fields.surrounding),
    learning_state: shortDict(fields.learning_state),
    recent_actions: recent,
    provenance: shortDict(fields.provenance),
  };
  for (const key of KEYS) {
    if (!(key in snapshot)) throw new Error(`缺少上下文键：${key}`);
  }
  return snapshot;
}

const STAGE_KEY = "learnsys:ask-context";
const STAGE_TTL_MS = 2 * 60 * 1000;

function _nonce() {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  } catch { /* 老浏览器没有 randomUUID */ }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * 从任意 App 打开学习助手，并把「当前题/资料/选中文本」作为快照带过去。
 * 快照只暂存一次（2 分钟），由助手页按 nonce 消费；`new=1` 强制新会话，
 * `ctx=nonce` 保证即使已经在 `#/ask` 也会触发 remount。
 */
export function openAssistant({ prompt = "", snapshot = null, materialId = 0 } = {}) {
  const token = _nonce();
  if (snapshot) {
    try {
      sessionStorage.setItem(STAGE_KEY, JSON.stringify({
        nonce: token, ts: Date.now(), snapshot,
      }));
    } catch { /* sessionStorage 满了也不拦着打开助手 */ }
  } else {
    try { sessionStorage.removeItem(STAGE_KEY); } catch { /* ignore */ }
  }
  const params = new URLSearchParams();
  if (prompt) params.set("prompt", prompt);
  if (Number(materialId || 0)) params.set("material", String(Number(materialId)));
  params.set("new", "1");
  params.set("ctx", token);
  location.hash = `#/ask?${params.toString()}`;
  return token;
}

/** 助手页消费暂存快照；nonce 不匹配或过期就丢弃。 */
export function takeStagedSnapshot(nonce = "") {
  let raw = "";
  try { raw = sessionStorage.getItem(STAGE_KEY) || ""; } catch { return null; }
  if (!raw) return null;
  let staged = null;
  try { staged = JSON.parse(raw); } catch { staged = null; }
  if (!staged || typeof staged !== "object") {
    try { sessionStorage.removeItem(STAGE_KEY); } catch { /* ignore */ }
    return null;
  }
  if (nonce && String(staged.nonce || "") !== String(nonce)) return null;
  if (Date.now() - Number(staged.ts || 0) > STAGE_TTL_MS) {
    try { sessionStorage.removeItem(STAGE_KEY); } catch { /* ignore */ }
    return null;
  }
  try { sessionStorage.removeItem(STAGE_KEY); } catch { /* ignore */ }
  try {
    return buildSnapshot(staged.snapshot || {});
  } catch {
    return null;
  }
}

/** 给界面看的一行摘要。 */
export function describeSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return "";
  const head = String(snapshot.title || snapshot.object_id || "当前上下文").trim();
  const selection = String(snapshot.selection || "").trim();
  if (!selection) return head;
  const short = selection.length > 30 ? `${selection.slice(0, 30)}…` : selection;
  return `${head} · ${short}`;
}
