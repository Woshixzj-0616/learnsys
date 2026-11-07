"""实践经验库接口：三格经验卡 CRUD、搜索、项目筛选、用到次数。

路由只做鉴权与错误码；校验在 `services.practice`，SQL 在 `store.practice`。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import practice as service

router = APIRouter()


class PracticeIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    scene: str = Field(min_length=1, max_length=4000)
    pitfall: str = Field(min_length=1, max_length=4000)
    next_time: str = Field(min_length=1, max_length=4000)
    kind: str = ""
    why: str = ""
    evidence: str = ""
    tags: str = ""
    project_id: int = 0
    source: str = "manual"
    source_id: str = ""


class PracticePatch(BaseModel):
    title: str | None = None
    scene: str | None = None
    pitfall: str | None = None
    next_time: str | None = None
    kind: str | None = None
    why: str | None = None
    evidence: str | None = None
    tags: str | None = None
    project_id: int | None = None
    status: str | None = None


def _conn():
    return store.connect()


@router.get("/api/practice")
def practice_list(q: str = "", tag: str = "", project_id: int = 0,
                  status: str = "active", limit: int = 200,
                  _=Depends(require_token)):
    conn = _conn()
    try:
        return service.list_notes(
            conn, query=q, tag=tag, project_id=project_id,
            status=status, limit=limit)
    finally:
        conn.close()


@router.post("/api/practice")
def practice_create(req: PracticeIn, _=Depends(require_token)):
    conn = _conn()
    try:
        return service.create(conn, req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/api/practice/{note_id}")
def practice_get(note_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        note = service.get(conn, note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return note
    finally:
        conn.close()


@router.patch("/api/practice/{note_id}")
def practice_update(note_id: int, req: PracticePatch,
                    _=Depends(require_token)):
    conn = _conn()
    try:
        note = service.update(conn, note_id, req.model_dump(exclude_unset=True))
        if note is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return note
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/api/practice/{note_id}/used")
def practice_used(note_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        note = service.used(conn, note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return note
    finally:
        conn.close()


@router.post("/api/practice/{note_id}/archive")
def practice_archive(note_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        note = service.archive(conn, note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return note
    finally:
        conn.close()


@router.delete("/api/practice/{note_id}")
def practice_delete(note_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        if not service.delete(conn, note_id):
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"deleted": note_id}
    finally:
        conn.close()
