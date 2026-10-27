"""P26.1 Agent 中枢接口：只读派活、增量事件、停止。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import config as app_config
from learnsys import store
from learnsys.services import agents
from learnsys.server.security import require_token

router = APIRouter()

MAX_PROMPT = 20000


class TaskIn(BaseModel):
    agent: str = Field(min_length=1, max_length=20)
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT)
    workspace: str = Field(default="", max_length=500)
    material_id: int = 0
    timeout: int = Field(default=0, ge=0, le=900)


def _task_or_404(conn, task_id: int) -> dict:
    task = store.get_agent_task(conn, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/api/agents")
def list_agents(_=Depends(require_token)):
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
    }


@router.post("/api/agents/tasks", status_code=201)
def create_task(req: TaskIn, _=Depends(require_token)):
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
        if store.agent_tasks_running(conn, agent=spec.id):
            raise HTTPException(
                status_code=409,
                detail=f"{spec.name} 已有一个任务在跑，等它结束再派。")
        if store.agent_tasks_running(conn) >= agents.max_concurrent(settings):
            raise HTTPException(status_code=409,
                                detail="同时运行的任务太多，等一个结束再派。")
        task_id = store.add_agent_task(
            conn, agent=spec.id, prompt=prompt,
            workspace=str(workspace), mode="read")
        run_timeout = max(10, min(int(req.timeout or 0), 900)) if req.timeout \
            else agents.timeout(settings)
        agents.start_task(
            task_id, spec, prompt, workspace, run_timeout,
            app_config.DATA_ROOT)
        task = store.get_agent_task(conn, task_id)
    finally:
        conn.close()
    return {"task": task}


@router.get("/api/agents/tasks")
def list_tasks(limit: int = 20, _=Depends(require_token)):
    conn = store.connect()
    try:
        return {"tasks": store.list_agent_tasks(conn, limit=limit)}
    finally:
        conn.close()


@router.get("/api/agents/tasks/{task_id}")
def get_task(task_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        return {"task": _task_or_404(conn, task_id)}
    finally:
        conn.close()


@router.get("/api/agents/tasks/{task_id}/events")
def task_events(task_id: int, after: int = 0, limit: int = 1000,
                _=Depends(require_token)):
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
    conn = store.connect()
    try:
        _task_or_404(conn, task_id)
    finally:
        conn.close()
    stopped = agents.cancel_task(task_id)
    if not stopped:
        raise HTTPException(status_code=409, detail="这个任务已经结束了")
    return {"ok": True, "id": int(task_id)}
