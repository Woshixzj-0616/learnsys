// 壳层：侧栏、hash 路由、页面生命周期。加模块只改 registry.json。
import { api, initApi } from "./api.js";
import { escapeHtml, setStatus, toast } from "./ui.js";

const PRODUCT_NAME = "学习工作台";

const view = document.getElementById("view");
const nav = document.getElementById("nav");
const titleNode = document.getElementById("page-title");
const subNode = document.getElementById("page-sub");
const actions = document.getElementById("page-actions");

let registry = [];
let prefs = {};
let current = { id: "", cleanup: null };
let seq = 0;
// 每次打开工作台换一个版本号：改完前端刷新即生效，不吃旧缓存
const BUILD = Math.floor(Date.now() / 1000);

function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const parts = pathPart.split("/").filter(Boolean);
  return {
    id: parts[0] || "today",
    params: parts.slice(1),
    query: new URLSearchParams(queryPart || ""),
  };
}

function moduleById(id) {
  return registry.find((item) => item.id === id) || null;
}

const SYSTEM_PLUGINS = new Set(["settings", "plugins"]);

function navItem(module, activeId) {
  const active = module.id === activeId ? " active" : "";
  const planned = module.status === "planned" ? " planned" : "";
  const flag = module.status === "planned" ? '<span class="nav-flag">待建</span>' : "";
  return `<a class="nav-item${active}${planned}" href="#/${module.id}" data-id="${escapeHtml(module.id)}"
             title="${escapeHtml(module.description || module.note || module.name)}">
    <span class="nav-icon" aria-hidden="true">${escapeHtml(module.icon || "·")}</span>
    <span class="nav-label">${escapeHtml(module.name)}</span>${flag}
  </a>`;
}

function navGroup(label, items, activeId) {
  if (!items.length) return "";
  return `<div class="nav-group-label">${escapeHtml(label)}</div>`
    + items.map((item) => navItem(item, activeId)).join("");
}

function renderNav(activeId) {
  const visible = registry.filter((module) => prefs[module.id] !== false);
  const ready = visible.filter((m) => m.status !== "planned" && !SYSTEM_PLUGINS.has(m.id));
  const planned = visible.filter((m) => m.status === "planned");
  const system = visible.filter((m) => SYSTEM_PLUGINS.has(m.id));
  nav.innerHTML = navGroup("舞台", ready, activeId)
    + navGroup("待建", planned, activeId)
    + navGroup("系统", system, activeId);
}

function setHeader(module) {
  titleNode.textContent = module.name;
  subNode.textContent = module.note || "";
  actions.innerHTML = "";
  document.title = `${module.name} · ${PRODUCT_NAME}`;
}

function renderPlanned(module) {
  view.innerHTML = `<div class="planned-page">
    <div class="planned-icon" aria-hidden="true">${escapeHtml(module.icon || "·")}</div>
    <h2>${escapeHtml(module.name)}</h2>
    <p>${escapeHtml(module.note || "这个模块还在建设中。")}</p>
    <a class="btn" href="#/today">回到今日</a>
  </div>`;
}

async function fetchPage(module) {
  const entry = String(module.entry || "").replace(/^\/+/, "");
  const response = await fetch(`/web/${entry}?v=${BUILD}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`页面没加载出来（${response.status}）`);
  return response.text();
}

async function navigate() {
  const route = parseRoute();
  const module = moduleById(route.id) || moduleById("today");
  if (!module) {
    view.innerHTML = `<div class="empty"><strong>没有可显示的插件</strong>检查
      <code>learnsys/plugins/*/plugin.json</code> 是否可读。</div>`;
    return;
  }

  const ticket = ++seq;
  if (current.id && current.cleanup) {
    try { current.cleanup(); } catch { /* 页面自己收尾失败不影响换页 */ }
  }
  current = { id: module.id, cleanup: null };
  renderNav(module.id);
  setHeader(module);

  if (module.status === "planned") {
    renderPlanned(module);
    return;
  }

  view.innerHTML = `<div class="empty">正在打开 ${escapeHtml(module.name)}…</div>`;
  try {
    // iframe 模块的 entry 是后端挂载的地址（如 /cet6/工作台/…），不是 /web/ 下的页面文件 ——
    // 不能走 fetchPage，否则会去 /web/cet6/… 拿一个 404。
    if (module.type === "iframe") {
      // 路由里的 query 原样带给 iframe（今日页「六级断点」→ ?paper= 直接回到该卷）
      const query = route.query.toString();
      const src = query
        ? `${module.entry}${module.entry.includes("?") ? "&" : "?"}${query}`
        : module.entry;
      view.innerHTML = `<iframe src="${escapeHtml(src)}" title="${escapeHtml(module.name)}"
        style="width:100%;height:100%;border:0;background:var(--bg)"></iframe>`;
      return;
    }

    const html = await fetchPage(module);
    if (ticket !== seq) return;
    view.innerHTML = html;

    if (!module.script) return;
    const script = String(module.script).replace(/^\/+/, "");
    const page = await import(`/web/${script}?v=${BUILD}`);
    if (ticket !== seq) return;

    const ctx = {
      root: view,
      params: route.params,
      query: route.query,
      module,
      registry,
      setSub(text) { subNode.textContent = text || ""; },
      setActions(html) { actions.innerHTML = html || ""; },
    };
    await page.mount(ctx);
    if (ticket !== seq) return;
    current.cleanup = typeof page.unmount === "function" ? page.unmount : null;
  } catch (error) {
    if (ticket !== seq) return;
    view.innerHTML = `<div class="empty"><strong>这个页面没打开</strong>
      ${escapeHtml(error?.message || error)}
      <div style="margin-top:14px"><button class="btn" id="retry-page">重试</button></div></div>`;
    document.getElementById("retry-page")?.addEventListener("click", navigate);
    console.error(error);
  }
}

// 后台没起来时：自动重试 + 「启动后台」按钮（发 learnsys:// 给 Windows，由本机程序接手）。
// PWA 壳是浏览器页面，自己起不了进程；这里能做的是把「没有后台」从死路变成一秒之内有救。
const RETRY_SECONDS = 3;
let retryTimer = null;
let booting = false;

function stopRetry() {
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
}

function startRetry() {
  stopRetry();
  let left = RETRY_SECONDS;
  const tick = () => {
    const node = document.getElementById("retry-left");
    if (node) node.textContent = String(left);
    if (left <= 0) {
      retryTimer = null;
      boot();
      return;
    }
    left -= 1;
    retryTimer = setTimeout(tick, 1000);
  };
  retryTimer = setTimeout(tick, 1000);
}

function showOffline(error) {
  setStatus("后台未连接", "err");
  view.innerHTML = `<div class="empty"><strong>连不上本地服务</strong>
    ${escapeHtml(error?.message || error)}
    <div class="hint" style="margin-top:8px">本地后台没在跑。点「启动后台」会拉起本机的学习工作台
      （第一次会问一次“是否允许打开”）；也可以双击桌面图标。</div>
    <div class="hint" style="margin-top:8px">正在自动重试：<span id="retry-left">${RETRY_SECONDS}</span> 秒</div>
    <div style="margin-top:14px">
      <button class="btn" id="retry-boot">立即重试</button>
      <button class="btn" id="launch-backend">启动后台</button>
    </div></div>`;
  document.getElementById("retry-boot")?.addEventListener("click", () => {
    stopRetry();
    boot();
  });
  document.getElementById("launch-backend")?.addEventListener("click", (event) => {
    event.currentTarget.disabled = true;
    location.href = "learnsys://start";   // 没注册这个协议就什么也不会发生，下面的重试兜底
  });
  startRetry();
}

async function boot() {
  if (booting) return;
  booting = true;
  stopRetry();
  try {
    const health = await initApi();
    document.getElementById("version").textContent = health.version || "";
    setStatus(`本地服务 ${health.port || ""}`.trim(), "ok");
    const data = await api.get("/api/modules");
    registry = Array.isArray(data.modules) ? data.modules : [];
    try {
      const settings = await api.get("/api/settings");
      prefs = settings.modules || {};
    } catch {
      prefs = {};                    // 设置读不到不耽误用工作台
    }
    await navigate();
  } catch (error) {
    showOffline(error);
    console.error(error);
  } finally {
    booting = false;
  }
}

window.addEventListener("hashchange", navigate);
window.addEventListener("learnsys:prefs", (event) => {
  if (event.detail && typeof event.detail === "object") {
    prefs = { ...prefs, ...event.detail };
    renderNav(current.id);
  }
});
window.addEventListener("unhandledrejection", (event) => {
  console.error(event.reason);
  toast(event.reason?.message || "出错了，详情看控制台", "err");
});

async function callQuickbar(kind) {
  try {
    await api.post(`/api/quickbar/${kind}`, {});
    toast(kind === "pick" ? "框选已打开：拖一块屏幕" : "快捷栏已叫到屏幕上方", "ok");
  } catch (error) {
    toast(error.message || "快捷栏没响应", "err");
  }
}

function bindQuickbarTools() {
  document.getElementById("ui-quickbar")?.addEventListener(
    "click", () => callQuickbar("show"));
  document.getElementById("ui-pick")?.addEventListener(
    "click", () => callQuickbar("pick"));
}

// ---- 离线壳：只注册 Service Worker，不再宣传装成 PWA ----
// 统一入口是桌面/开始菜单的「学习工作台」快捷方式；再装一个 PWA 会多出第二个窗口。
function bindServiceWorker() {
  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" })
      .catch((error) => console.warn("Service Worker 没注册上（不影响在线使用）：", error));
  }
}

bindQuickbarTools();
bindServiceWorker();
boot();
