"""本地服务的安全边界。

- 只监听 127.0.0.1；
- 写接口要 `X-Learnsys-Token`（启动时随机生成，同源页面从 /api/health 拿）；
- 跨源请求按 Origin 白名单拦截 —— 恶意网页连「发请求」这一步都过不去；
- 六级工作台如果仍从 file:// 打开，只放行 `/analyze` 和 `/api/cet6/*` 的 `null` 源。
"""
from __future__ import annotations

import secrets

from fastapi import HTTPException, Request


def token_from_request(request: Request) -> str:
    token = request.headers.get("x-learnsys-token") or ""
    if not token:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    return token


def require_token(request: Request) -> None:
    """FastAPI 依赖：令牌不对直接 403。"""
    expected = str(getattr(request.app.state, "token", "") or "")
    given = token_from_request(request)
    if not expected or not secrets.compare_digest(given, expected):
        raise HTTPException(status_code=403, detail="缺少或错误的本地令牌")


def allowed_origins(port: int) -> set[str]:
    return {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:8766",
        "http://localhost:8766",
    }


def origin_allowed(origin: str, path: str, port: int) -> bool:
    """没有 Origin（curl / 同源导航）放行；有 Origin 就必须在白名单里。

    `null` 是 file:// 页面的 Origin：只允许六级分析 / 同步 / 迁移这几个接口，
    不允许它调 Agent 或数据写接口。
    """
    if not origin:
        return True
    if origin in allowed_origins(port):
        return True
    if origin == "null":
        return path == "/analyze" or path.startswith("/api/cet6/")
    return False
