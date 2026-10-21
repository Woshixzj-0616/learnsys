/* 学习台 Service Worker：只缓存「壳」，不碰 API / 六级 iframe / 音频。
 *
 * 目标：PWA 能装、断网时至少能打开壳并提示「后台未连接」；
 * 数据永远走本地 FastAPI，不在这里缓存。
 */
const CACHE = "learnsys-web-v2";
const CORE = [
  "/",
  "/manifest.webmanifest",
  "/web/icons/icon-192.png",
  "/web/icons/icon-512.png",
  "/web/icons/icon-maskable-512.png",
  "/web/icons/apple-touch-icon.png",
  "/web/index.html",
  "/web/css/tokens.css",
  "/web/css/app.css",
  "/web/js/shell.js",
  "/web/js/api.js",
  "/web/js/ui.js",
  "/web/js/markdown.js",
  "/web/pages/today.html",
  "/web/pages/ask.html",
  "/web/pages/settings.html",
  "/web/pages/plugins.html",
  "/web/pages/netlab.html",
  "/web/pages/review.html",
  "/web/pages/quiz.html",
  "/web/js/pages/today.js",
  "/web/js/pages/ask.js",
  "/web/js/pages/settings.js",
  "/web/js/pages/plugins.js",
  "/web/js/pages/netlab.js",
  "/web/js/pages/review.js",
  "/web/js/pages/quiz.js",
  "/web/vendor/marked.min.js",
  "/web/vendor/purify.min.js",
  "/web/vendor/highlight.min.js",
  "/web/vendor/highlight-dark.css",
  "/web/vendor/katex/katex.min.js",
  "/web/vendor/katex/katex.min.css",
  "/web/vendor/katex/auto-render.min.js"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(CORE))
      .catch(() => null)          // 少一个文件不该让 SW 装不上
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE)
        .map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

function cacheable(request, response) {
  return request.method === "GET"
    && response
    && response.status === 200
    && response.type === "basic"
    && new URL(request.url).origin === self.location.origin;
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (cacheable(request, response)) {
      const cache = await caches.open(CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await caches.match(request);
    if (cached) return cached;
    if (request.mode === "navigate") {
      const shell = await caches.match("/");
      if (shell) return shell;
    }
    throw error;
  }
}

async function staleWhileRevalidate(request) {
  const cached = await caches.match(request);
  const network = fetch(request).then((response) => {
    if (cacheable(request, response)) {
      caches.open(CACHE).then((cache) => cache.put(request, response.clone()));
    }
    return response;
  }).catch(() => null);
  return cached || network;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/cet6/")
      || url.pathname === "/docs" || url.pathname.startsWith("/docs/")
      || url.pathname === "/favicon.ico") {
    return;                         // API / 六级 / 文档 / 图标：交给网络
  }
  const isShell = request.mode === "navigate"
    || url.pathname === "/"
    || url.pathname === "/manifest.webmanifest"
    || url.pathname.startsWith("/web/");
  event.respondWith(isShell ? networkFirst(request) : staleWhileRevalidate(request));
});
