"""P26.2 Agent 中枢接口：只读/可写派活、逐条审批、增量事件、停止。

P26.3 起建任务先入队；队列位次与影子路由建议随任务返回。
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import agents

router = APIRouter()

MAX_PROMPT = 20000
WRITE_WAIT_SECONDS = 0.25


class TaskIn(BaseModel):
    agent: str = Field(min_length=1, max_length=20)
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT)
    workspace: str = Field(default="", max_length=500)
    material_id: int = 0
    mode: str = Field(default="read", pattern="^(read|write)$")
    timeout: int = Field(default=0, ge=0, le=900)
    depends_on: int = Field(default=0, ge=0)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(allow|deny)$")
    note: str = Field(default="", max_length=500)


def _ready() -> None:
    """首次访问中枢时恢复上次中断的任务并接续队列。"""
    agents.queue.ensure_started()


def _task_or_404(conn, task_id: int) -> dict:
    task = store.get_agent_task(conn, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _check_parent(parent: dict | None) -> None:
    if parent is None:
        raise HTTPException(status_code=404, detail="上一步任务不存在")
    if parent["status"] in ("failed", "cancelled"):
        raise HTTPException(status_code=409,
                            detail="上一步任务已失败或已取消，不能接续。")
    if parent["status"] == "done" and not parent.get("has_result"):
        raise HTTPException(
            status_code=409,
            detail="上一步任务没有文本结果，不能接续；换一个任务试试。")


def _route_json(conn, spec, *, mode: str, chosen: str,
                settings: dict) -> str:
    """影子路由建议；算不出来就留空，绝不挡住派活。"""
    try:
        other_id = "codex" if chosen == "claude" else "claude"
        other = agents.spec_for(other_id, settings)
        available = {chosen: bool(spec.available)}
        names = {chosen: spec.name}
        if other is not None:
            available[other_id] = bool(other.available)
            names[other_id] = other.name
        history = {
            agent_id: store.agent_recent_terminal(conn, agent_id, mode)
            for agent_id in (chosen, other_id)
        }
        data = agents.route.recommend(
            mode=mode, chosen=chosen, available=available,
            history=history, names=names)
        return json.dumps(data, ensure_ascii=False)[:2000]
    except Exception:
        return ""


@router.get("/api/agents")
def list_agents(_=Depends(require_token)):
    _ready()
    settings = agents.settings()
    return {
        "agents": [
            {"id": spec.id, "name": spec.name, "available": spec.available,
             "version": spec.version, "note": spec.note}
            for spec in agents.list_specs(settings)
        ],
        "allowed_roots": [str(root) for root in agents.allowed_roots(settings)],
        "default_workspace": str(agents.default_workspace(settings)),
        "timeout": agents.timeout(settings),
        "max_concurrent": agents.max_concurrent(settings),
        "queue_max": agents.queue_max(settings),
    }


@router.post("/api/agents/tasks", status_code=201)
def create_task(req: TaskIn, _=Depends(require_token)):
    _ready()
    settings = agents.settings()
    spec = agents.spec_for(req.agent, settings)
    if spec is None:
        raise HTTPException(status_code=404, detail="没有这个 agent")
    if not spec.available:
        raise HTTPException(status_code=409,
                            detail=spec.note or f"{spec.name} 现在不可用")
    workspace, reason = agents.resolve_workspace(req.workspace, settings)
    if workspace is None:
        raise HTTPException(status_code=400, detail=reason)

    prompt = str(req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="任务内容是空的")

    conn = store.connect()
    try:
        if req.material_id:
            material = store.get_material(conn, int(req.material_id), with_body=True)
            if material is None:
                raise HTTPException(status_code=404, detail="资料不存在")
            body = str(material.get("body") or "")[:MAX_PROMPT]
            prompt = (f"{prompt}\n\n【资料 #{material.get('id')}："
                      f"{material.get('title') or '未命名'}】\n{body}")
            prompt = prompt[:MAX_PROMPT]
        parent = None
        if req.depends_on:
            parent = store.get_agent_task(conn, int(req.depends_on))
            _check_parent(parent)
            if len(prompt) > MAX_PROMPT - 1800:
                raise HTTPException(
                    status_code=400,
                    detail="任务内容太长：接续任务要给上一步结果留出空间"
                           f"（不超过 {MAX_PROMPT - 1800} 字）。")
        timeout_s = max(10, min(int(req.timeout or 0), 900)) if req.timeout else 0
        task_id = store.add_agent_queued_task(
            conn, agent=spec.id, prompt=prompt, workspace=str(workspace),
            mode=req.mode, timeout_s=timeout_s, depends_on=req.depends_on,
            route_json=_route_json(conn, spec, mode=req.mode, chosen=spec.id,
                                   settings=settings),
            queue_max=agents.queue_max(settings))
        if task_id is None:
            # 插入内已同时判断父状态与队列上限，这里复查一次区分原因
            latest = store.get_agent_task(conn, int(req.depends_on)) \
                if req.depends_on else None
            if req.depends_on:
                _check_parent(latest)
            raise HTTPException(
                status_code=429,
                detail="排队任务太多（含等待上一步的任务），等几个跑完再派。")
    finally:
        conn.close()
    agents.queue.schedule_drain()
    conn = store.connect()
    try:
        task = store.get_agent_task(conn, task_id) or {}
    finally:
        conn.close()
    return {"task": task, "queue_position": int(task.get("queue_position") or 0)}


@router.get("/api/agents/tasks")
def list_tasks(limit: int = 20, _=Depends(require_token)):
    _ready()
    conn = store.connect()
    try:
        return {"tasks": store.list_agent_tasks(conn, limit=limit)}
    finally:
        conn.close()


@router.get("/api/agents/tasks/{task_id}")
def get_task(task_id: int, _=Depends(require_token)):
    _ready()
    conn = store.connect()
    try:
        return {"task": _task_or_404(conn, task_id)}
    finally:
        conn.close()


@router.get("/api/agents/tasks/{task_id}/events")
def task_events(task_id: int, after: int = 0, limit: int = 1000,
                _=Depends(require_token)):
    _ready()
    conn = store.connect()
    try:
        task = _task_or_404(conn, task_id)
        events = store.list_agent_task_events(conn, task_id, after=after, limit=limit)
    finally:
        conn.close()
    return {"task": task, "events": events,
            "next": events[-1]["seq"] if events else int(after or 0)}


@router.post("/api/agents/tasks/{task_id}/cancel")
def cancel_task(task_id: int, _=Depends(require_token)):
    _ready()
    conn = store.connect()
    try:
        task = _task_or_404(conn, task_id)
    finally:
        conn.close()
    if task["status"] in ("done", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail="这个任务已经结束了")
    if agents.queue.cancel(task_id):
        return {"ok": True, "id": int(task_id)}
    conn = store.connect()
    try:
        current = store.get_agent_task(conn, task_id) or {}
    finally:
        conn.close()
    if current.get("status") == "cancelled":
        return {"ok": True, "id": int(task_id)}
    raise HTTPException(status_code=409, detail="这个任务已经结束了")


@router.get("/api/agents/tasks/{task_id}/approvals")
def task_approvals(task_id: int, after: int = 0, limit: int = 200,
                   _=Depends(require_token)):
    conn = store.connect()
    try:
        task = _task_or_404(conn, task_id)
        items = store.list_agent_approvals(conn, task_id, after=after, limit=limit)
    finally:
        conn.close()
    return {"task": task, "approvals": items,
            "next": items[-1]["id"] if items else int(after or 0)}


@router.post("/api/agents/approvals/{approval_id}/decide")
def decide_approval(approval_id: int, req: DecisionIn,
                    _=Depends(require_token)):
    conn = store.connect()
    try:
        approval = store.get_agent_approval(conn, approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="这条提议不存在")
        if approval["status"] != "pending":
            raise HTTPException(status_code=409, detail="这条提议已经处理过了")
        status = "allowed" if req.decision == "allow" else "denied"
        reason = req.note.strip() or (
            "用户在界面允许" if status == "allowed" else "用户在界面拒绝")
        if not store.decide_agent_approval(conn, approval_id, status, reason):
            raise HTTPException(status_code=409, detail="这条提议已经处理过了")
        approval = store.get_agent_approval(conn, approval_id)
    finally:
        conn.close()
    return {"ok": True, "approval": approval}


@router.post("/api/agents/hooks/approval")
def hook_approval(payload: dict, request: Request):
    """Claude 的 PreToolUse 钩子入口：落一条提议，原地等到用户点允许/拒绝。

    钩子令牌只能提交提议，**不能替用户做决定**；决定接口仍要网页令牌。
    """
    token = request.headers.get("x-learnsys-hook") or ""
    claimed = request.headers.get("x-learnsys-task") or ""
    task_id = agents.approvals.task_for(token)
    if not task_id or str(task_id) != str(claimed):
        raise HTTPException(status_code=403, detail="审批令牌不对")

    tool = str(payload.get("tool_name") or "")
    if tool not in agents.approvals.GATED_TOOLS:
        return agents.approvals.allow("这个工具不需要逐条确认")
    described = agents.approvals.describe(
        tool, payload.get("tool_input") if isinstance(payload, dict) else {})

    wait_s = agents.approval_timeout()
    status = "expired"
    conn = store.connect()
    try:
        task = store.get_agent_task(conn, task_id)
        if task is None or task["status"] not in ("queued", "running"):
            return agents.approvals.deny("任务已经结束")
        approval_id = store.add_agent_approval(
            conn, task_id=task_id, tool=tool, **described)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            row = store.get_agent_approval(conn, approval_id)
            if row is None:
                break
            status = row["status"]
            if status != "pending":
                break
            current = store.get_agent_task(conn, task_id)
            if current is None or current["status"] in (
                    "done", "failed", "cancelled"):
                store.decide_agent_approval(
                    conn, approval_id, "expired", "任务已结束")
                status = "expired"
                break
            time.sleep(WRITE_WAIT_SECONDS)
        if status == "pending":
            store.decide_agent_approval(
                conn, approval_id, "expired", "等待确认超时")
            status = "expired"
    finally:
        conn.close()

    if status == "allowed":
        return agents.approvals.allow("用户已允许这次操作")
    if status == "denied":
        return agents.approvals.deny("用户拒绝了这次操作")
    return agents.approvals.deny("等待确认超时，已按拒绝处理")
