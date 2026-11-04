"""六级专项听写接口：队列、提交、统计。

路由只做鉴权和错误码；差异/建卡/统计都在 `services.cet6_drill`，
SQL 只在 `store.cet6_drill`。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services.cet6 import drill as service

router = APIRouter()


class AttemptIn(BaseModel):
    paper_id: str = Field(min_length=1, max_length=300)
    section: str = Field(min_length=1, max_length=120)
    item: str = Field(min_length=1, max_length=120)
    sentence: int = Field(ge=1, le=9999)
    answer: str = Field(default="", max_length=4000)
    duration_s: int = Field(default=0, ge=0, le=3600)


def _conn():
    return store.connect()


@router.get("/api/cet6/drill/queue")
def drill_queue(limit: int = 8, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.queue(conn, limit=limit)
    finally:
        conn.close()


@router.post("/api/cet6/drill/attempt")
def drill_attempt(req: AttemptIn, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.attempt(conn, req.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/api/cet6/drill/stats")
def drill_stats(days: int = 30, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.stats(conn, days=days)
    finally:
        conn.close()
