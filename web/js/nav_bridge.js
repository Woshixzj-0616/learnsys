// B1 深链桥：Qt 写「待跳转」，这里按 seq 增量应用。
// 路由解析只在 shell.js 里有一份；本文件只负责把 location.hash 换成目标值。
import { api } from "./api.js";

const POLL_MS = 2000;

/** 纯函数：根据本地状态与服务端快照，决定要不要跳、跳到哪。 */
export function nextRoute(state, payload) {
  const current = {
    server: String(state?.server || ""),
    last: Number(state?.last) || 0,
  };
  const server = String(payload?.server || "");
  if (!server) return { state: current, href: "" };
  // 后台重启后 seq 从头开始；不归零的话，新序号永远追不上旧的。
  const last = current.server && current.server !== server ? 0 : current.last;
  const seq = Number(payload?.seq) || 0;
  const href = typeof payload?.href === "string" ? payload.href : "";
  if (!href || seq <= last) return { state: { server, last }, href: "" };
  return { state: { server, last: seq }, href };
}

let installed = false;

/**
 * 前台每 2 秒拉一次；聚焦/回到前台立刻拉一次（Qt 点击会把窗口提到前台）。
 * 只安装一次；返回卸载函数（测试用）。
 */
export function installNavBridge(options = {}) {
  if (installed) return () => {};
  installed = true;
  const intervalMs = Math.max(500, Number(options.intervalMs) || POLL_MS);
  let state = { server: "", last: 0 };
  let busy = false;

  async function poll() {
    if (busy) return;
    busy = true;
    try {
      const data = await api.get(`/api/ui/navigate?since=${state.last}`);
      const next = nextRoute(state, data);
      state = next.state;
      if (next.href && location.hash !== next.href) location.hash = next.href;
    } catch {
      // 后台断开时静默；恢复后 server 变化或下一轮继续。
    } finally {
      busy = false;
    }
  }

  const pollIfVisible = () => {
    if (!document.hidden) poll();
  };
  window.addEventListener("focus", poll);
  document.addEventListener("visibilitychange", pollIfVisible);
  const timer = setInterval(pollIfVisible, intervalMs);
  poll();

  return () => {
    clearInterval(timer);
    window.removeEventListener("focus", poll);
    document.removeEventListener("visibilitychange", pollIfVisible);
    installed = false;
  };
}
