"""Web 工作台调原生快捷栏：叫出来 / 直接开始框选。

没有 AskApp 在跑时（例如单独启动后端做开发），返回 503，让页面说人话。
B1 起还提供「待跳转」队列：Qt 深链点击先写这里，Web 壳按 seq 拉取。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from learnsys.server import runtime
from learnsys.server.security import require_token

router = APIRouter()


def _call(name: str, message: str) -> dict:
    if not runtime.call_ui(name):
        raise HTTPException(status_code=503, detail=message)
    return {"ok": True}


class NavigateRequest(BaseModel):
    href: str = ""


def _bridge(request: Request):
    bridge = getattr(request.app.state, "nav_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="待跳转队列没初始化")
    return bridge


@router.post("/api/ui/navigate")
def request_navigate(body: NavigateRequest, request: Request,
                     _=Depends(require_token)):
    """Qt 点击深链：记下目标。Web 页面在前台轮询或聚焦时取走。"""
    try:
        seq = _bridge(request).set(body.href)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "seq": seq}


@router.get("/api/ui/navigate")
def read_navigate(request: Request, since: int = Query(0, ge=0),
                  _=Depends(require_token)):
    """读取最新一条。`since` 为兼容保留；是否应用由前端按 server+seq 判断。"""
    data = _bridge(request).snapshot()
    data["since"] = int(since)
    return data


@router.post("/api/quickbar/show")
def show_quickbar(_=Depends(require_token)):
    return _call("show_bar", "快捷栏没在运行：先打开学习工作台")


@router.post("/api/quickbar/pick")
def pick_on_screen(_=Depends(require_token)):
    return _call("pick", "快捷栏没在运行：先打开学习工作台")


@router.get("/api/quickbar/record")
def record_state(_=Depends(require_token)):
    """Web 工作台的「开始录像」按钮轮询：录像中 / 收尾中 / 倒计时。"""
    state = runtime.call_state("record")
    if state is None:
        raise HTTPException(status_code=503, detail="后台没接在快捷栏上，无法读取录像状态")
    return state


@router.post("/api/quickbar/record")
def toggle_record(_=Depends(require_token)):
    """Web 工作台点「开始/停止录像」—— 和横栏、托盘、快捷键同一个开关。"""
    return _call("record", "快捷栏没在跑，无法开始录像")
