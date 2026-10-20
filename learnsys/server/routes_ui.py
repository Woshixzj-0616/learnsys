"""Web 工作台调原生快捷栏：叫出来 / 直接开始框选。

没有 AskApp 在跑时（例如单独启动后端做开发），返回 503，让页面说人话。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from learnsys.server import runtime
from learnsys.server.security import require_token

router = APIRouter()


def _call(name: str, message: str) -> dict:
    if not runtime.call_ui(name):
        raise HTTPException(status_code=503, detail=message)
    return {"ok": True}


@router.post("/api/quickbar/show")
def show_quickbar(_=Depends(require_token)):
    return _call("show_bar", "快捷栏没在运行：先打开问一问")


@router.post("/api/quickbar/pick")
def pick_on_screen(_=Depends(require_token)):
    return _call("pick", "快捷栏没在运行：先打开问一问")
