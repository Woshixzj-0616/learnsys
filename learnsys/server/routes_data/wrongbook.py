"""错题本接口：列表、手动补收、复习、掌握、删除、导出、旧收藏切换。"""
from __future__ import annotations

import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import review as review_service
from .common import _conn

router = APIRouter()


class WrongAddIn(BaseModel):
    source: str = "manual"          # quiz / manual
    conversation_id: int | None = None
    material_id: int = 0
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(default="", max_length=8000)
    my_answer: str = Field(default="", max_length=4000)
    tags: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=8000)


class WrongReviewIn(BaseModel):
    result: str = Field(default="remember", pattern="^(remember|forgot)$")


class WrongMasterIn(BaseModel):
    mastered: bool = True


@router.get("/api/wrongbook")
def wrongbook(status: str = "all", source: str = "", limit: int = 200,
              material_id: int = 0, _=Depends(require_token)):
    conn = _conn()
    try:
        return {
            "items": store.wrong_items(conn, status=status, source=source,
                                       limit=limit, material_id=material_id),
            "counts": store.wrong_counts(conn),
            "materials": store.wrong_material_facets(conn),
        }
    finally:
        conn.close()


@router.post("/api/wrongbook")
def add_wrongbook(req: WrongAddIn, _=Depends(require_token)):
    """手动补收 / 测验前端补收；同题按来源+指纹去重。"""
    conn = _conn()
    try:
        source = req.source if req.source in ("quiz", "manual") else "manual"
        question = req.question.strip()
        if source == "quiz":
            ref = int(req.conversation_id or 0)
            source_id = f"quiz:{ref}:{store.wrong_fingerprint(question)}"
        else:
            source_id = f"manual:{store.wrong_fingerprint(question)}"
        item_id, created = store.add_wrong_item(
            conn, question=question, answer=req.answer, my_answer=req.my_answer,
            tags=req.tags, note=req.note, source=source, source_id=source_id,
            material_id=req.material_id)
        return {"ok": True, "id": item_id, "created": created,
                "item": store.get_wrong_item(conn, item_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/api/wrongbook/{item_id}/review")
def review_wrongbook(item_id: int, req: WrongReviewIn, _=Depends(require_token)):
    conn = _conn()
    try:
        rating = 1 if str(req.result or "").strip().lower() == "forgot" else 3
        try:
            state = review_service.review(conn, "wrong", item_id, rating)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="这道错题不在了") from exc
        item = store.get_wrong_item(conn, item_id)
        return {"ok": True, "item": item, **state}
    finally:
        conn.close()


@router.post("/api/wrongbook/{item_id}/master")
def master_wrongbook(item_id: int, req: WrongMasterIn, _=Depends(require_token)):
    conn = _conn()
    try:
        if not store.set_wrong_mastered(conn, item_id, req.mastered):
            raise HTTPException(status_code=404, detail="这道错题不在了")
        return {"ok": True, "item": store.get_wrong_item(conn, item_id)}
    finally:
        conn.close()


@router.delete("/api/wrongbook/{item_id}")
def delete_wrongbook(item_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        if not store.delete_wrong_item(conn, item_id):
            raise HTTPException(status_code=404, detail="这道错题不在了")
        return {"ok": True, "id": item_id}
    finally:
        conn.close()


@router.get("/api/wrongbook/export")
def export_wrongbook(_=Depends(require_token)):
    """全部错题 → Anki CSV（utf-8-sig）。导出是只读操作，走 GET。"""
    from learnsys.services import study as study_mod
    conn = _conn()
    try:
        items = store.wrong_items(conn, status="all", limit=1000)
        text = study_mod.wrongbook_csv_text(items)
    finally:
        conn.close()
    filename = f"错题本_{datetime.date.today():%Y%m%d}.csv"
    return Response(
        content=("﻿" + text).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.post("/api/wrongbook/{ask_id}/toggle")
def toggle_wrongbook(ask_id: int, _=Depends(require_token)):
    """旧路径保留：问答收藏 = 收进 / 移出错题本。"""
    conn = _conn()
    try:
        state = store.toggle_star(conn, ask_id)
        return {"id": ask_id, "starred": bool(state)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"改错题本失败：{exc}") from exc
    finally:
        conn.close()
