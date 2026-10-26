// 提交后的轮询：写作与翻译共用；关页由调用方 stop()。
import { api } from "../../api.js";

export function pollSubmission(id, handlers = {}) {
  const {
    onReviewed, onFailed, onTimeout, onError, onTick,
    timeoutMs = 180000, intervalMs = 2000,
  } = handlers;
  const started = Date.now();
  let timer = null;
  let ticker = null;
  let stopped = false;

  const stop = () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    if (ticker) clearInterval(ticker);
    timer = null;
    ticker = null;
  };

  if (onTick) {
    ticker = setInterval(
      () => onTick(Math.round((Date.now() - started) / 1000)), 1000);
  }

  const run = async () => {
    if (stopped) return;
    try {
      const data = await api.get(`/api/cet6/train/submissions/${id}`);
      if (stopped) return;
      if (data.status === "reviewed") {
        stop();
        onReviewed?.(data);
        return;
      }
      if (data.status === "failed") {
        stop();
        onFailed?.(data);
        return;
      }
      if (Date.now() - started > timeoutMs) {
        stop();
        onTimeout?.(data);
        return;
      }
      timer = setTimeout(run, intervalMs);
    } catch (error) {
      stop();
      onError?.(error);
    }
  };

  timer = setTimeout(run, 1200);
  return { stop };
}
