// 六级 AI 的上下文装配：九键快照只在这里拼一次，页面 provider 只补对象事实。
import { buildSnapshot } from "../../context.js";

// 六级训练六个标签的显示名；上下文标题与建议问题都按这个键取。
export const TAB_NAMES = {
  listening: "精听", drill: "专项", writing: "写作",
  translation: "翻译", review: "复习", stats: "统计",
  daily: "每日积累",
};

export function safeProvider(provider) {
  if (typeof provider !== "function") return null;
  try {
    const data = provider();
    return data && typeof data === "object" ? data : null;
  } catch {
    return null;
  }
}

/**
 * 组装九键信号；页面 provider 可覆盖 object_type / object_id / title /
 * surrounding / learning_state，surface 与来源固定为六级训练。
 */
export function collectContext({ activeTab, tabNames, selection, recentActions, provider }) {
  const fields = {
    surface: "cet6",
    object_type: "cet6_tab",
    object_id: activeTab,
    title: `六级训练 · ${tabNames[activeTab] || "训练"}`,
    selection: selection || "",
    surrounding: {},
    learning_state: {},
    recent_actions: (recentActions || []).slice(-10),
    provenance: { page: "cet6", tab: activeTab },
  };
  const extra = safeProvider(provider);
  if (extra) {
    if (extra.object_type) fields.object_type = String(extra.object_type);
    if (extra.object_id) fields.object_id = String(extra.object_id);
    if (extra.title) fields.title = String(extra.title);
    if (extra.surrounding && typeof extra.surrounding === "object") {
      fields.surrounding = extra.surrounding;
    }
    if (extra.learning_state && typeof extra.learning_state === "object") {
      fields.learning_state = extra.learning_state;
    }
  }
  return fields;
}

/** 组装后立刻校验一次，避免发送时才发现缺键。 */
export function snapshotOf(options) {
  return buildSnapshot(collectContext(options));
}

export function contextLine({ activeTab, tabNames, selection, provider }) {
  const extra = safeProvider(provider);
  const title = extra?.title || `六级训练 · ${tabNames[activeTab] || "训练"}`;
  const picked = String(selection || "").replace(/\s+/g, " ").trim();
  const tail = picked ? ` · 已带选中「${picked.length > 18 ? `${picked.slice(0, 18)}…` : picked}」` : "";
  return `正在看：${title}${tail}`;
}
