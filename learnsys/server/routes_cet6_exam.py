"""六级真题自评接口：队列、提交、统计。

路由只做鉴权和错误码；题干/音频路径在 `services.cet6_paper`，
自评与统计在 `services.cet6_exam`，SQL 只在 `store.cet6_exam`。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services.cet6 import exam as service

router = APIRouter()


class ExamAttemptIn(BaseModel):
    paper_id: str = Field(min_length=1, max_length=300)
    section: str = Field(min_length=1, max_length=120)
    item: str = Field(min_length=1, max_length=120)
    wrong: list[int] = Field(default_factory=list)
    duration_s: int = Field(default=0, ge=0, le=3600)


def _conn():
    return store.connect()


@router.get("/api/cet6/exam/queue")
def exam_queue(limit: int = 1, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.queue(conn, limit=limit)
    finally:
        conn.close()


@router.post("/api/cet6/exam/attempt")
def exam_attempt(req: ExamAttemptIn, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.attempt(conn, req.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/api/cet6/exam/stats")
def exam_stats(days: int = 30, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.stats(conn, days=days)
    finally:
        conn.close()
