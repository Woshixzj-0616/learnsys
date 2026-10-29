"""插件事件：网工训练、复盘打卡等时间线事件。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from .common import _conn

router = APIRouter()


class EventIn(BaseModel):
    module: str = Field(min_length=1, max_length=40)
    kind: str = Field(default="note", max_length=40)
    title: str = Field(default="", max_length=200)
    meta: dict = Field(default_factory=dict)


@router.post("/api/events")
def add_event(req: EventIn, _=Depends(require_token)):
    """插件写一条学习事件（网工训练场完成训练、复盘打卡等）。"""
    conn = _conn()
    try:
        stamp = store.now()
        event_id = store.add_event(
            conn, req.module.strip(), req.kind.strip() or "note",
            req.title.strip(), req.meta)
        return {"ok": True, "id": event_id, "ts": stamp}
    finally:
        conn.close()


@router.get("/api/events")
def list_events(module: str = "", limit: int = 50, _=Depends(require_token)):
    limit = max(1, min(int(limit or 50), 200))
    conn = _conn()
    try:
        return {"items": store.list_events(conn, module=module, limit=limit)}
    finally:
        conn.close()
