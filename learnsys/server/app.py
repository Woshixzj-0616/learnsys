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
from fastapi.responses import HTMLResponse, JSONResponse, Response

from learnsys import config
from learnsys.agent.config import load_config
from learnsys.ask import VERSION
from learnsys.server import routes_agent, routes_cet6, routes_data
from learnsys.server.security import origin_allowed

DEFAULT_PORT = 8765


def create_app(token: str | None = None, port: int = DEFAULT_PORT) -> FastAPI:
    app = FastAPI(title="学习系统", version=VERSION, docs_url="/docs", redoc_url=None)
    app.state.token = token or os.environ.get("LEARNSYS_TOKEN") or secrets.token_urlsafe(24)
    app.state.port = port

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
        }

    @app.get("/", response_class=HTMLResponse)
    def root():
        """P3 之前先给一个能点的占位页；真正的 Web 工作台在 P3。"""
        return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>学习系统 · 后台</title>
<style>body{{background:#1b1e23;color:#dfe6ee;font-family:'Microsoft YaHei UI',sans-serif;
padding:40px;line-height:1.7}}a{{color:#6ea8ff}}code{{color:#f5b74e}}</style>
<h1>学习系统后台已启动</h1>
<p>版本 {VERSION} · 服务在 127.0.0.1:{port}</p>
<ul>
<li><a href="/api/health">/api/health</a> —— 存活、模型、令牌</li>
<li><a href="/docs">/docs</a> —— 接口文档</li>
<li><a href="/api/today">/api/today</a> —— 今日概览（要令牌）</li>
</ul>
<p>Web 工作台在 P3；现在快捷栏已经用同一个 Agent。</p></html>"""

    return app


class _ThreadServer(uvicorn.Server):
    """在后台线程里跑：不用装信号处理器（非主线程装会抛 ValueError）。"""

    def install_signal_handlers(self) -> None:   # noqa: D401
        return


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


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
