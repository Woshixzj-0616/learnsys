// 结构化上下文快照：九键白名单、截断、20KB 上限。
// 口径与后端 `learnsys/context.py` 保持一致；页面只构造，不再自己拼大段字符串。

export const MAX_BYTES = 20 * 1024;
export const MAX_SELECTION = 2000;
export const MAX_TITLE = 200;
export const MAX_SURROUNDING = 1000;
export const MAX_RECENT_ACTIONS = 20;

const KEYS = [
  "surface", "object_type", "object_id", "title", "selection",
  "surrounding", "learning_state", "recent_actions", "provenance",
];

function text(value, cap) {
  const raw = String(value ?? "");
  return raw.length <= cap ? raw : raw.slice(0, cap);
}

function shortDict(value, cap) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof key !== "string") continue;
    if (typeof item === "string") out[key] = text(item, cap);
    else if (typeof item === "number" || typeof item === "boolean" || item === null) out[key] = item;
    else if (Array.isArray(item)) out[key] = item.slice(0, 20).map((x) => text(x, cap));
    else if (item && typeof item === "object") {
      const inner = {};
      for (const [k, v] of Object.entries(item)) {
        if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
          inner[String(k)] = text(v, cap);
        }
      }
      out[key] = inner;
    }
  }
  return out;
}

function action(value) {
  if (typeof value === "string") return text(value, 300);
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const out = {};
    for (const [key, item] of Object.entries(value)) {
      if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
        out[String(key)] = text(item, 300);
      }
    }
    return out;
  }
  return null;
}

/** 按九键白名单构造快照；未知键丢弃，超 20KB 抛错。 */
export function buildSnapshot(fields = {}) {
  if (!fields || typeof fields !== "object" || Array.isArray(fields)) {
    throw new Error("上下文必须是对象");
  }
  const recent = [];
  for (const item of (Array.isArray(fields.recent_actions) ? fields.recent_actions : []).slice(0, MAX_RECENT_ACTIONS)) {
    const one = action(item);
    if (one !== null) recent.push(one);
  }
  const snapshot = {
    surface: text(fields.surface, 40),
    object_type: text(fields.object_type, 40),
    object_id: text(fields.object_id, 300),
    title: text(fields.title, MAX_TITLE),
    selection: text(fields.selection, MAX_SELECTION),
    surrounding: shortDict(fields.surrounding, MAX_SURROUNDING),
    learning_state: shortDict(fields.learning_state, MAX_SURROUNDING),
    recent_actions: recent,
    provenance: shortDict(fields.provenance, 300),
  };
  for (const key of KEYS) {
    if (!(key in snapshot)) throw new Error(`缺少上下文键：${key}`);
  }
  const bytes = new TextEncoder().encode(JSON.stringify(snapshot)).length;
  if (bytes > MAX_BYTES) {
    throw new Error("上下文太大（超过 20KB），先少选一点内容");
  }
  return snapshot;
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
