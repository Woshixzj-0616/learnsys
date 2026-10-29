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

/** 给界面看的一行摘要。 */
export function describeSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return "";
  const head = String(snapshot.title || snapshot.object_id || "当前上下文").trim();
  const selection = String(snapshot.selection || "").trim();
  if (!selection) return head;
  const short = selection.length > 30 ? `${selection.slice(0, 30)}…` : selection;
  return `${head} · ${short}`;
}
