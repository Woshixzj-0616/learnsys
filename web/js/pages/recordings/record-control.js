// 录像页顶部的「开始/停止录像」：轮询 /api/quickbar/record，和快捷栏/托盘同一个开关。
import { api } from "../../api.js";
import { toast } from "../../ui.js";

export function createRecordControl({ button, formatDuration, onFinished }) {
  let timer = null;
  let state = null;
  let ready = true;

  function paint() {
    if (!button) return;
    button.disabled = !ready || Boolean(state?.finishing);
    if (!ready) {
      button.textContent = "录像不可用";
      button.title = "后台没接在快捷栏上（用开发后台时正常）";
      return;
    }
    button.title = "和快捷栏、托盘、Ctrl+Alt+S 是同一个开关";
    const countdown = Number(state?.countdown || 0);
    if (state?.finishing) {
      button.textContent = "收尾中…";
    } else if (countdown > 0) {
      button.textContent = `取消倒计时 ${countdown}`;
    } else if (state?.recording) {
      button.textContent = `停止录像 · ${formatDuration(state.duration)}`;
    } else {
      button.textContent = "开始录像";
    }
  }

  async function refresh() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    const wasActive = Boolean(state && (state.recording || state.finishing));
    try {
      const next = await api.get("/api/quickbar/record");
      ready = true;
      state = next;
      paint();
      if (wasActive && !(next.recording || next.finishing) && onFinished) await onFinished();
      const active = next && (next.recording || next.finishing || next.countdown > 0);
      timer = setTimeout(refresh, active ? 1200 : 5000);
    } catch (error) {
      ready = false;
      state = null;
      paint();
      timer = setTimeout(refresh, 8000);
    }
  }

  async function toggle() {
    if (!ready) {
      toast("后台没接在快捷栏上，先在电脑上打开学习工作台");
      return;
    }
    if (state?.finishing) return;
    const idle = !state || (!state.recording && !state.countdown);
    try {
      await api.post("/api/quickbar/record");
      if (idle) toast("3 秒后开始录像 —— 切换到你录的窗口");
      await refresh();
    } catch (error) {
      toast(error.message);
    }
  }

  const focus = () => { refresh(); };
  window.addEventListener("focus", focus);
  button?.addEventListener("click", toggle);
  paint();

  return {
    refresh,
    dispose() {
      if (timer) clearTimeout(timer);
      timer = null;
      window.removeEventListener("focus", focus);
      button?.removeEventListener("click", toggle);
    },
  };
}
