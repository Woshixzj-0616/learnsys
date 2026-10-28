// Agent 中枢的纯展示函数：状态、耗时、标题。
export const STATUS_TEXT = {
  queued: "排队中",
  running: "运行中",
  done: "完成",
  failed: "失败",
  cancelled: "已取消",
};

export function statusText(status) {
  return STATUS_TEXT[status] || status || "—";
}

export function queueText(task) {
  const position = Number(task?.queue_position) || 0;
  return position > 0 ? `排队中 · 第 ${position} 位` : "排队中";
}

export function routeText(route, agents = []) {
  const recommended = route?.recommended;
  if (!recommended) return "";
  const name = agentName(recommended, agents);
  if (recommended === route.chosen) {
    return `路由建议（影子）：与建议一致（${name}）`;
  }
  const reason = String(route.reason || "").trim();
  return `路由建议（影子）：建议 ${name}${reason ? ` · ${reason}` : ""}；本次按你的选择执行`;
}

export function msText(ms) {
  const value = Number(ms) || 0;
  if (value < 1000) return `${value} 毫秒`;
  if (value < 60000) return `${(value / 1000).toFixed(1)} 秒`;
  return `${Math.floor(value / 60000)} 分 ${Math.round((value % 60000) / 1000)} 秒`;
}

export function modeText(mode) {
  return mode === "write" ? "可写" : "只读";
}

export function agentName(id, agents = []) {
  return agents.find((item) => item.id === id)?.name || id || "—";
}

export function taskTitle(task, agents = []) {
  const name = agentName(task?.agent, agents);
  return `${name} · 任务 #${task?.id ?? "—"}`;
}

export function promptPreview(text, cap = 90) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value.length > cap ? `${value.slice(0, cap)}…` : value;
}
