// 浏览器插件页：状态、打开网址、暂停记录、历史。前端只调 /api/browser/*，不接触调试端口。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

let nodes = {};
let timer = null;
let busy = false;

export async function mount(ctx) {
  ctx.setSub("独立窗口 + 本机浏览记录；只记录 URL、标题和域名");
  ctx.setActions('<a class="btn" href="#/ask">去问一问</a>');
  nodes = {
    dot: ctx.root.querySelector("#browser-dot"),
    state: ctx.root.querySelector("#browser-state"),
    current: ctx.root.querySelector("#browser-current"),
    launch: ctx.root.querySelector("#browser-launch"),
    close: ctx.root.querySelector("#browser-close"),
    url: ctx.root.querySelector("#browser-url"),
    open: ctx.root.querySelector("#browser-open"),
    record: ctx.root.querySelector("#browser-record"),
    clear: ctx.root.querySelector("#browser-clear"),
    history: ctx.root.querySelector("#browser-history"),
  };
  nodes.launch.addEventListener("click", launch);
  nodes.close.addEventListener("click", close);
  nodes.open.addEventListener("click", openTyped);
  nodes.url.addEventListener("keydown", (event) => {
    if (event.key === "Enter") openTyped();
  });
  nodes.record.addEventListener("click", toggleRecording);
  nodes.clear.addEventListener("click", clearHistory);
  nodes.history.addEventListener("click", reopen);
  await refresh();
  timer = setInterval(refresh, 3000);
}

export function unmount() {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

function setBusy(value) {
  busy = value;
  for (const key of ["launch", "close", "open", "record", "clear"]) {
    if (nodes[key]) nodes[key].disabled = value;
  }
}

async function refresh() {
  try {
    const [status, history] = await Promise.all([
      api.get("/api/browser/status"),
      api.get("/api/browser/history?limit=60&days=30"),
    ]);
    renderStatus(status);
    renderHistory(history.items);
  } catch (error) {
    nodes.state.textContent = `读取失败：${error.message || error}`;
  }
}

function renderStatus(status) {
  const running = Boolean(status.running);
  const paused = Boolean(status.paused);
  nodes.dot.className = `browser-dot ${running ? (paused ? "paused" : "on") : "off"}`;
  if (!status.enabled) {
    nodes.state.textContent = "浏览器功能已在设置里关闭";
  } else if (!running) {
    nodes.state.textContent = status.message || "未启动";
  } else {
    nodes.state.textContent = paused ? "运行中 · 记录已暂停" : "运行中";
  }
  const current = status.current;
  nodes.current.textContent = current
    ? `${current.title || "（无标题）"} — ${current.url || ""}`
    : "";
  nodes.current.title = nodes.current.textContent;
  nodes.launch.disabled = running || busy;
  nodes.close.disabled = !running || busy;
  nodes.record.disabled = !running || busy;
  nodes.record.textContent = paused ? "恢复记录" : "暂停记录";
}

function renderHistory(items) {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    nodes.history.innerHTML = '<div class="empty">还没有记录。打开一个网页后，这里会出现时间、标题和域名。</div>';
    return;
  }
  nodes.history.innerHTML = list.map((item) => `
    <div class="browser-row">
      <time>${escapeHtml(String(item.ts || "").slice(5, 16))}</time>
      <div class="browser-row-main">
        <strong title="${escapeHtml(item.title || "")}">${escapeHtml(item.title || "（无标题）")}</strong>
        <span>${escapeHtml(item.domain || "")} · ${escapeHtml(item.url || "")}</span>
      </div>
      <button class="btn browser-reopen" type="button"
              data-url="${escapeHtml(item.url || "")}">重新打开</button>
    </div>`).join("");
}

async function launch() {
  if (busy) return;
  setBusy(true);
  nodes.state.textContent = "正在启动浏览器…";
  try {
    const status = await api.post("/api/browser/launch", {});
    if (!status.running) toast(status.message || "浏览器没启动起来");
    renderStatus(status);
  } catch (error) {
    toast(`启动失败：${error.message || error}`);
  } finally {
    setBusy(false);
    refresh();
  }
}

async function close() {
  if (busy) return;
  setBusy(true);
  try {
    const status = await api.post("/api/browser/close", {});
    renderStatus(status);
    toast("浏览器已关闭");
  } catch (error) {
    toast(`关闭失败：${error.message || error}`);
  } finally {
    setBusy(false);
    refresh();
  }
}

async function openTyped() {
  const url = nodes.url.value.trim();
  if (!url) {
    toast("先输入一个网址");
    return;
  }
  await openUrl(url);
}

async function openUrl(url) {
  if (busy) return;
  setBusy(true);
  try {
    const result = await api.post("/api/browser/open", { url });
    toast(result.message || "已打开");
    if (result.ok) nodes.url.value = "";
  } catch (error) {
    toast(error.message || "网址没有打开");
  } finally {
    setBusy(false);
    setTimeout(refresh, 800);
  }
}

async function toggleRecording() {
  if (busy) return;
  setBusy(true);
  try {
    const current = await api.get("/api/browser/status");
    const result = await api.post("/api/browser/recording", {
      enabled: !current.record,
    });
    renderStatus(result.status);
    toast(result.message);
  } catch (error) {
    toast(`切换失败：${error.message || error}`);
  } finally {
    setBusy(false);
  }
}

async function clearHistory() {
  if (!window.confirm("清空全部浏览记录？不会关闭浏览器，也不会删除 Cookie 和缓存。")) {
    return;
  }
  try {
    const result = await api.del("/api/browser/history");
    toast(result.message || "已清空");
    await refresh();
  } catch (error) {
    toast(`清空失败：${error.message || error}`);
  }
}

function reopen(event) {
  const button = event.target.closest(".browser-reopen");
  if (!button) return;
  const url = button.dataset.url || "";
  if (url) openUrl(url);
}
