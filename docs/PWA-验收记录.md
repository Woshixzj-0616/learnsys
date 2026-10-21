# PWA 验收记录 · 学习台安装与离线壳（阶段 B）

> 日期：2026-10-21 ｜ 版本：`2.0.0` ｜ 状态：完成

## 为什么做

桌面壳路线选了「网页内核 + 薄壳」，第一步是 PWA：不重写 UI，先让学习台能安装成独立窗口，
并保留浏览器可调试的路径。原生重写（阶段 D）不做。

## 落地

| 文件 | 作用 |
|---|---|
| `web/manifest.webmanifest` | 名称、`start_url: "/"`、`scope: "/"`、`standalone`、图标、快捷方式 |
| `web/sw.js` | 根作用域 Service Worker：只缓存页面壳，跳过 `/api/`、`/cet6/`、`/docs` |
| `learnsys/server/app.py` | `/manifest.webmanifest`（`application/manifest+json`）、`/sw.js`（`Service-Worker-Allowed: /`） |
| `web/index.html` | `rel=manifest`、theme-color、apple-touch-icon、侧栏「安装学习台」按钮 |
| `web/js/shell.js` | 注册 SW、`beforeinstallprompt`、安装按钮、`appinstalled` |
| `web/icons/` | 192 / 512 / maskable 512 / apple-touch 180 四个 PNG |

## 实测

- `navigator.serviceWorker`: `active / activated / scope=http://127.0.0.1:8765/`，`controller=true`。
- 缓存：`learnsys-web-v2` 里 30 个条目，`/` 命中且状态 200。
- `beforeinstallprompt` 已触发，侧栏「安装学习台」按钮显示（`installHidden=false`）。
- 断网（CDP Offline）后导航 `/`：
  - 壳与 CSS/JS 从缓存打开，标题「学习系统」；
  - 页面显示「连不上本地服务 / 后台未连接」，重试按钮在；
  - 回到在线后刷新恢复正常。
- 静态测试 `tests/test_pwa.py` 5 例：清单 MIME、SW 根作用域、预缓存文件全部存在、index 链接/注册、图标 PNG 头。

## 边界

- 断网只保证**壳**能打开；问答、插件数据、六级音频仍需要本地 FastAPI。
- 安装入口由浏览器决定（Edge/Chrome）；Safari/Firefox 的行为不在本轮目标。
- PWA 仍跑在浏览器引擎里，任务栏进程归 Edge；想要完全自有进程再进阶段 C（WebView2 薄壳）。
