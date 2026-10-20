"""学习系统本地服务：一个进程里同时提供 Agent、数据、六级分析。

地址固定 127.0.0.1:8765 —— 六级工作台里硬编码的 `/analyze` 不用改。
写接口要令牌；跨源按 Origin 白名单拦截；详情见 `security.py`。
"""
from __future__ import annotations

import os
import secrets
import socket
import threading

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from learnsys import config
from learnsys.agent.config import load_config
from learnsys.ask import VERSION
from learnsys.modules import web_dir
from learnsys.server import (routes_agent, routes_cet6, routes_data, routes_settings,
                             routes_ui, routes_upload, routes_web, runtime)
from learnsys.server.security import origin_allowed

DEFAULT_PORT = 8765


def create_app(token: str | None = None, port: int = DEFAULT_PORT) -> FastAPI:
    app = FastAPI(title="学习系统", version=VERSION, docs_url="/docs", redoc_url=None)
    app.state.token = token or os.environ.get("LEARNSYS_TOKEN") or secrets.token_urlsafe(24)
    app.state.port = port

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
    app.include_router(routes_cet6.router)
    app.include_router(routes_web.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_upload.router)
    app.include_router(routes_ui.router)

    assets = web_dir()
    if (assets / "index.html").exists():
        app.mount("/web", StaticFiles(directory=str(assets), html=True), name="web")

    @app.get("/api/health")
    def health():
        cfg = load_config()
        return {
            "ok": True,
            "version": VERSION,
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

    @app.get("/", response_class=HTMLResponse)
    def root():
        """Web 工作台；`web/` 还没放进来时退回一个能点的占位页。"""
        if index.exists():
            return FileResponse(index)
        return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>学习系统 · 后台</title>
<style>body{{background:#1b1e23;color:#dfe6ee;font-family:'Microsoft YaHei UI',sans-serif;
padding:40px;line-height:1.7}}a{{color:#6ea8ff}}</style>
<h1>学习系统后台已启动</h1>
<p>版本 {VERSION} · 服务在 127.0.0.1:{port}</p>
<p>没找到 <code>web/index.html</code>，Web 工作台还没装进来。</p>
<ul><li><a href="/api/health">/api/health</a> —— 存活、模型、令牌</li></ul></html>"""

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        icon = config.ROOT / "问一问.ico"
        if icon.exists():
            return FileResponse(icon)
        return Response(status_code=204)

    return app


class _ThreadServer(uvicorn.Server):
    """在后台线程里跑：不用装信号处理器（非主线程装会抛 ValueError）。"""

    def install_signal_handlers(self) -> None:   # noqa: D401
        return


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    """端口能不能用：**先试着连一下**，连得上 = 有人已经在监听。

    不能用 `bind()` 探：Windows 的 SO_REUSEADDR 允许两个进程同时绑同一端口，
    会把“已被占用”误判成空闲，最后两个服务抢同一条连接。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        try:
            sock.connect((host, port))
        except socket.timeout:
            return False         # 没拒绝也没接受 = 当它有人在，别去抢
        except OSError:
            return True          # 拒绝连接 = 没人监听
        return False             # 连上了 = 已占用


def serve_in_thread(port: int = DEFAULT_PORT) -> _ThreadServer:
    """起一个后台服务线程；端口被占就抛 RuntimeError，由调用方给中文提示。"""
    if not port_free(port):
        raise RuntimeError(f"端口 {port} 被占用（可能旧的 启动分析服务.bat 还在跑）")
    server = _ThreadServer(uvicorn.Config(
        create_app(port=port), host="127.0.0.1", port=port,
        log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, name="learnsys-server", daemon=True)
    thread.start()
    return server


def main() -> int:
    uvicorn.run(create_app(), host="127.0.0.1", port=DEFAULT_PORT,
                log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
