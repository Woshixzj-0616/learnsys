"""「调用路径」页的只读接口 + 本机代理。

- `GET /api/agent-trace`：最近 /api/chat 的 trace 列表（可过滤 username）
- `GET /api/agent-trace/{trace_id}`：单条完整流水
- `POST /api/agent-trace/login`：把用户名 / 密码转给本机智能旅行 `/api/login`，拿回令牌
- `POST /api/agent-trace/chat`：带令牌把一轮消息转发给 `/api/chat`，SSE 原样回流

只允许本机 8000 / 8001 的智能旅行后端（防 SSRF）；不存令牌、不写库。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from learnsys.server.security import require_token
from learnsys.store import agent_trace

router = APIRouter()

DEFAULT_BASE = "http://127.0.0.1:8000"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
ALLOWED_PORTS = {8000, 8001}


class TravelLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)
    base: str = ""


class TravelChatIn(BaseModel):
    messages: list[dict]
    session_id: str = ""
    message_id: str = ""
    base: str = ""


def _base(raw: str) -> str:
    """只允许本机 8000 / 8001；其余一律拒，避免这个代理被拿去做 SSRF。"""
    text = str(raw or "").strip() or DEFAULT_BASE
    parsed = urlparse(text)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (parsed.scheme not in ("http", "https")
            or parsed.hostname not in ALLOWED_HOSTS
            or port not in ALLOWED_PORTS):
        raise HTTPException(status_code=400,
                            detail="只允许本机 8000 / 8001 的智能旅行后端")
    return text.rstrip("/")


@router.get("/api/agent-trace")
def list_traces(limit: int = 30, username: str = "", _=Depends(require_token)):
    return agent_trace.list_recent(limit=limit, username=username)


@router.get("/api/agent-trace/{trace_id}")
def get_trace(trace_id: str, _=Depends(require_token)):
    row = agent_trace.get(trace_id)
    if row is None:
        raise HTTPException(status_code=404, detail="这条 trace 不在了，或者旅行库读不到")
    return row


@router.post("/api/agent-trace/login")
def travel_login(req: TravelLoginIn, _=Depends(require_token)):
    base = _base(req.base)
    body = json.dumps({"username": req.username, "password": req.password},
                      ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/login", data=body, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise HTTPException(status_code=400, detail="智能旅行登录失败：%s" % detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="连不上智能旅行后端：%s" % exc) from exc
    token = str(payload.get("token") or "")
    if not token:
        raise HTTPException(status_code=502, detail="智能旅行没有返回令牌")
    return {"ok": True, "token": token,
            "username": str(payload.get("username") or req.username)}


@router.post("/api/agent-trace/chat")
async def travel_chat(req: TravelChatIn,
                      x_travel_token: str = Header(default=""),
                      _=Depends(require_token)):
    if not x_travel_token.strip():
        raise HTTPException(status_code=401, detail="还没有登录智能旅行")
    base = _base(req.base)
    payload = {"messages": req.messages,
               "session_id": req.session_id,
               "message_id": req.message_id}

    async def relay():
        try:
            # 旅行后端自己有 80 秒预算；这里留到 120 秒，避免连接挂死时页面一直转。
            timeout = httpx.Timeout(120.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                        "POST", base + "/api/chat", json=payload,
                        headers={"Authorization": "Bearer " + x_travel_token.strip()}
                ) as response:
                    if response.status_code >= 400:
                        text = (await response.aread()).decode("utf-8", "replace")[:300]
                        yield "data: " + json.dumps(
                            {"proxy_error": "智能旅行 %s：%s" % (response.status_code, text)},
                            ensure_ascii=False) + "\n\n"
                        return
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except Exception as exc:
            yield "data: " + json.dumps(
                {"proxy_error": "转发失败：%s" % exc}, ensure_ascii=False) + "\n\n"

    return StreamingResponse(relay(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
