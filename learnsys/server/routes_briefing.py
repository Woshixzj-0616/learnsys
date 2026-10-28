"""每日简报接口：当天、历史、手动生成、已读/收藏。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from learnsys.server.security import require_token
from learnsys.services import briefing

router = APIRouter()


class GenerateIn(BaseModel):
    day: str = ""
    force: bool = False


class ItemPatch(BaseModel):
    read: bool | None = None
    starred: bool | None = None


class ReadAllIn(BaseModel):
    day: str = ""


@router.get("/api/briefing/today")
def briefing_today(_=Depends(require_token)):
    try:
        return briefing.today()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/briefing/days")
def briefing_days(limit: int = 30, _=Depends(require_token)):
    return {"items": briefing.days(limit=limit)}


@router.get("/api/briefing")
def briefing_get(day: str = "", _=Depends(require_token)):
    try:
        return briefing.get(day) if day else briefing.today()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/briefing/generate", status_code=202)
def briefing_generate(req: GenerateIn | None = None, _=Depends(require_token)):
    req = req or GenerateIn()
    try:
        return briefing.submit(req.day, force=req.force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/briefing/items/{item_id}")
def briefing_item(item_id: int, req: ItemPatch, _=Depends(require_token)):
    try:
        item = briefing.update_item(item_id, read=req.read, starred=req.starred)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="没有这条简报")
    return {"item": item}


@router.post("/api/briefing/read-all")
def briefing_read_all(req: ReadAllIn, _=Depends(require_token)):
    try:
        return {"updated": briefing.mark_all_read(req.day)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
