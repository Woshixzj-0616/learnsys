"""工作台浏览器接口：启动 / 打开 / 状态 / 历史 / 暂停记录 / 关闭。

端口、PID、profile 路径**不返回给前端**；写操作一律要令牌。
URL 校验与 Agent 工具共用 `learnsys.browser.urls.normalize_url`（单一落点）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys.browser.manager import get_manager
from learnsys.server.security import require_token

router = APIRouter()


class OpenRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class RecordingRequest(BaseModel):
    enabled: bool = True


@router.post("/api/browser/launch")
def launch_browser(_=Depends(require_token)):
    return get_manager().launch()


@router.post("/api/browser/open")
def open_url(req: OpenRequest, _=Depends(require_token)):
    try:
        result = get_manager().open_url(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/api/browser/status")
def browser_status(_=Depends(require_token)):
    return get_manager().status()


@router.get("/api/browser/history")
def browser_history(limit: int = 20, days: int = 7, domain: str = "",
                    _=Depends(require_token)):
    limit = max(1, min(100, int(limit or 20)))
    days = max(0, min(365, int(days or 0)))
    items = get_manager().history(limit=limit, days=days, domain=domain)
    return {"items": items, "count": len(items)}


@router.delete("/api/browser/history")
def clear_history(_=Depends(require_token)):
    cleared = get_manager().clear_history()
    return {"ok": True, "cleared": cleared, "message": f"已清空 {cleared} 条浏览记录"}


@router.post("/api/browser/recording")
def set_recording(req: RecordingRequest, _=Depends(require_token)):
    status = get_manager().set_recording(req.enabled)
    return {"ok": True, "status": status,
            "message": "已恢复记录" if req.enabled else "已暂停记录"}


@router.post("/api/browser/close")
def close_browser(_=Depends(require_token)):
    return get_manager().close(force=True)
