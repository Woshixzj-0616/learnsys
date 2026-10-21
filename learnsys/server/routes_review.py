"""P14 统一复习队列接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import review

router = APIRouter()


class ReviewIn(BaseModel):
    rating: int = Field(description="1 忘了 / 2 模糊 / 3 记得 / 4 简单")


@router.get("/api/review/queue")
def review_queue(limit: int = 50, item_type: str = "",
                 _=Depends(require_token)):
    conn = store.connect()
    try:
        return review.queue(conn, limit=limit, item_type=item_type)
    finally:
        conn.close()


@router.post("/api/review/{item_type}/{item_id}")
def submit_review(item_type: str, item_id: int, req: ReviewIn,
                  _=Depends(require_token)):
    conn = store.connect()
    try:
        return review.review(conn, item_type, item_id, req.rating)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/api/review/stats")
def review_stats(item_type: str = "", _=Depends(require_token)):
    conn = store.connect()
    try:
        return review.stats(conn, item_type=item_type)
    finally:
        conn.close()


@router.get("/api/review/log")
def review_log(limit: int = 20, _=Depends(require_token)):
    conn = store.connect()
    try:
        return review.recent_log(conn, limit=limit)
    finally:
        conn.close()
