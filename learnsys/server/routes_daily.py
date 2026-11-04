"""每日积累接口：当天三条线、条目状态、翻译词入生词本、往期。

路由只做鉴权和错误码；生成与统计在 `services.daily_accum`，
SQL 在 `store.daily_accum`。
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services.cet6 import daily_accum as service

router = APIRouter()


class StatusIn(BaseModel):
    status: str = Field(default="read", max_length=20)


def _conn():
    return store.connect()


def _day(value: str) -> str:
    text = str(value or "").strip()[:10]
    if not text:
        return dt.date.today().isoformat()
    try:
        dt.date.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from exc
    return text


@router.get("/api/daily")
def daily_day(day: str = "", _=Depends(require_token)):
    conn = _conn()
    try:
        return service.list_day(conn, _day(day))
    finally:
        conn.close()


@router.post("/api/daily/item/{item_id}/status")
def daily_status(item_id: int, req: StatusIn, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.mark(conn, item_id, req.status)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/api/daily/read-all")
def daily_read_all(day: str = "", _=Depends(require_token)):
    conn = _conn()
    try:
        return service.mark_all(conn, _day(day))
    finally:
        conn.close()


@router.post("/api/daily/term/{item_id}/vocab")
def daily_term_vocab(item_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.add_term_to_vocab(conn, item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/api/daily/history")
def daily_history(limit: int = 30, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.history(conn, limit=limit)
    finally:
        conn.close()
