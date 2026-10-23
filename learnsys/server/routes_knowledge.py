"""知识点与答题流水：作答上报、类目统计、最近答题、旧错题回填。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import knowledge as service

router = APIRouter()


class AttemptIn(BaseModel):
    conversation_id: int = 0
    material_id: int = 0
    question_no: int = 0
    question: str = ""
    my_answer: str = ""
    correct: bool | None = None
    feedback: str = ""
    points: list[str] = Field(default_factory=list)


class BackfillIn(BaseModel):
    dry_run: bool = False
    force: bool = False


@router.post("/api/quiz/attempt")
def quiz_attempt(req: AttemptIn, _=Depends(require_token)):
    conn = store.connect()
    try:
        try:
            return service.add_attempt(
                conn, question=req.question, my_answer=req.my_answer,
                correct=req.correct, conversation_id=req.conversation_id,
                material_id=req.material_id, question_no=req.question_no,
                feedback=req.feedback, points=req.points)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/api/knowledge")
def knowledge_stats(days: int = 0, _=Depends(require_token)):
    conn = store.connect()
    try:
        return service.attempt_stats(conn, days=days)
    finally:
        conn.close()


@router.get("/api/knowledge/{point_id}/attempts")
def knowledge_point_attempts(point_id: int, limit: int = 20, offset: int = 0,
                             days: int = 0, _=Depends(require_token)):
    conn = store.connect()
    try:
        data = service.point_attempts(
            conn, point_id, limit=limit, offset=offset, days=days)
        if data is None:
            raise HTTPException(status_code=404, detail="这个知识点不存在")
        return data
    finally:
        conn.close()


@router.post("/api/knowledge/backfill")
def knowledge_backfill(req: BackfillIn, _=Depends(require_token)):
    conn = store.connect()
    try:
        return service.backfill_wrong_items(
            conn, dry_run=req.dry_run, force=req.force)
    finally:
        conn.close()
