"""学习工作台本地服务：一个进程里同时提供 Agent、数据、六级分析。

地址固定 127.0.0.1:8765 —— 六级工作台里硬编码的 `/analyze` 不用改。
写接口要令牌；跨源按 Origin 白名单拦截；详情见 `security.py`。
"""
from __future__ import annotations

import datetime
import os
import secrets
import socket
import threading
import time
import traceback
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from learnsys import config, product
from learnsys.llm.config import load_config
from learnsys.modules import web_dir
from learnsys.server import (routes_agent, routes_browser, routes_cet6, routes_data,
                             routes_knowledge, routes_materials, routes_memory,
                             routes_recordings, routes_results, routes_review,
                             routes_services, routes_settings, routes_ui,
                             routes_upload, routes_vocab, routes_web, runtime)
from learnsys.server.nav_bridge import NavBridge
from learnsys.server.security import origin_allowed

DEFAULT_PORT = 8765


@asynccontextmanager
async def _lifespan(_app):
    yield
    try:
        from learnsys.browser.manager import get_manager
        get_manager().shutdown()     # close_on_exit=false 时什么也不做
    except Exception:
        pass


def create_app(token: str | None = None, port: int = DEFAULT_PORT) -> FastAPI:
    app = FastAPI(title=product.PRODUCT_NAME, version=product.VERSION, docs_url="/docs",
                  redoc_url=None, lifespan=_lifespan)
    app.state.token = token or os.environ.get("LEARNSYS_TOKEN") or secrets.token_urlsafe(24)
    app.state.port = port
    app.state.nav_bridge = NavBridge()     # B1 深链桥：Qt 写、Web 壳按 seq 取

    @app.middleware("http")
    async def no_store_web(request, call_next):
        """工作台是本地文件，改完刷新就要生效 —— 别让浏览器拿旧 JS/CSS。"""
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/web/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware("http")
    async def guard(request, call_next):
        origin = request.headers.get("origin") or ""
        path = request.url.path
        if not origin_allowed(origin, path, port):
            return JSONResponse({"detail": "跨源请求被拒绝"}, status_code=403)
        if request.method == "OPTIONS":
            response = Response(status_code=204)
        else:
            response = await call_next(request)
        if origin and origin_allowed(origin, path, port):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "content-type, x-learnsys-token"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    app.include_router(routes_agent.router)
    app.include_router(routes_data.router)
    app.include_router(routes_materials.router)
    app.include_router(routes_cet6.router)
    app.include_router(routes_vocab.router)
    app.include_router(routes_results.router)
    app.include_router(routes_services.router)
    app.include_router(routes_review.router)
    app.include_router(routes_knowledge.router)
    app.include_router(routes_web.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_memory.router)
    app.include_router(routes_upload.router)
    app.include_router(routes_ui.router)
    app.include_router(routes_browser.router)
    app.include_router(routes_recordings.router)

    # 六级精听（可选模块）：工作台 + 试卷挂到 /cet6/；没装就跳过，主功能不受影响
    routes_cet6.mount_static(app)

    assets = web_dir()
    if (assets / "index.html").exists():
        app.mount("/web", StaticFiles(directory=str(assets), html=True), name="web")

    @app.get("/api/health")
    def health():
        cfg = load_config()
        return {
            "ok": True,
            "version": product.VERSION,
            "model": cfg.model,
            "vision_ready": cfg.vision_ready,
            "token": app.state.token,
            "port": port,
            "db": str(config.db_path()),
            # true = 这个后台接在 Qt 主进程上，页面能调快捷栏；
            # 单独起的开发后台是 false，App 启动时不会复用它
            "quickbar": runtime.available(),
        }

    index = web_dir() / "index.html"

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        """PWA 清单：显式 MIME，StaticFiles 对 .webmanifest 不一定认得。"""
        path = web_dir() / "manifest.webmanifest"
        if not path.exists():
            return Response(status_code=204)
        return FileResponse(path, media_type="application/manifest+json",
                            headers={"Cache-Control": "no-store"})

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        """Service Worker 放根路径，作用域才是整个学习台（/web/sw.js 只能管 /web）。"""
        path = web_dir() / "sw.js"
        if not path.exists():
            return Response(status_code=204)
        return FileResponse(path, media_type="application/javascript",
                            headers={"Service-Worker-Allowed": "/",
                                     "Cache-Control": "no-store"})

    @app.get("/", response_class=HTMLResponse)
    def root():
        """Web 工作台；`web/` 还没放进来时退回一个能点的占位页。"""
        if index.exists():
            return FileResponse(index)
        return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>{product.PRODUCT_NAME} · 后台</title>
<style>body{{background:#1b1e23;color:#dfe6ee;font-family:'Microsoft YaHei UI',sans-serif;
padding:40px;line-height:1.7}}a{{color:#6ea8ff}}</style>
<h1>{product.PRODUCT_NAME}后台已启动</h1>
<p>版本 {product.VERSION} · 服务在 127.0.0.1:{port}</p>
<p>没找到 <code>web/index.html</code>，Web 工作台还没装进来。</p>
<ul><li><a href="/api/health">/api/health</a> —— 存活、模型、令牌</li></ul></html>"""

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        icon = config.ICON_PATH
        if icon.exists():
            return FileResponse(icon, headers={"Cache-Control": "no-store"})
        return Response(status_code=204)

    return app


class _ThreadServer(uvicorn.Server):
    """在后台线程里跑：不用装信号处理器（非主线程装会抛 ValueError）。"""

    def install_signal_handlers(self) -> None:   # noqa: D401
        return


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    """端口能不能用。

    两段判定：
    1. 连得上 = 已占用；被明确拒绝 = 空闲；
    2. **连接超时**（真机上见过：没有任何监听时 SYN 被安全软件丢掉，不返回 RST）
       改用 `bind()` 探。Windows 的 `SO_REUSEADDR` 允许多个进程绑同一端口，
       所以这里用 `SO_EXCLUSIVEADDRUSE`：已有服务在先，独占绑定会失败 → 判断为占用。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        try:
            sock.connect((host, port))
        except socket.timeout:
            pass                 # 超时不能下结论，走下面的 bind 探测
        except OSError:
            return True          # 拒绝连接 = 没人监听
        else:
            return False         # 连上了 = 已占用

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _log_server_error(exc: BaseException) -> None:
    """后台线程里的异常在无黑框 exe 里看不到 —— 落到数据目录，方便排查。"""
    try:
        path = config.DATA_ROOT / "启动错误.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        pass


def serve_in_thread(port: int = DEFAULT_PORT) -> _ThreadServer:
    """起一个后台服务线程；端口被占 / 线程没起来都抛 RuntimeError，调用方给中文提示。"""
    if not port_free(port):
        raise RuntimeError(f"端口 {port} 被占用（可能旧的 启动分析服务.bat 还在跑）")
    server = _ThreadServer(uvicorn.Config(
        create_app(port=port), host="127.0.0.1", port=port,
        log_level="warning", access_log=False))

    def run() -> None:
        try:
            server.run()
        except BaseException as exc:          # 线程里抛出去没人接，先记下来再退出
            server.start_error = exc
            _log_server_error(exc)

    thread = threading.Thread(target=run, name="learnsys-server", daemon=True)
    thread.start()
    # 等它真的开始监听：uvicorn 在 thread 里绑定失败时，serve_in_thread 原来会误报成功
    for _ in range(80):
        if getattr(server, "started", False):
            return server
        if not thread.is_alive():
            break
        time.sleep(0.05)
    error = getattr(server, "start_error", None)
    if error is None:
        error = RuntimeError("服务线程 4 秒内没有开始监听")
        _log_server_error(error)
    raise RuntimeError(f"服务没起来：{error}")


def main() -> int:
    uvicorn.run(create_app(), host="127.0.0.1", port=DEFAULT_PORT,
                log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
