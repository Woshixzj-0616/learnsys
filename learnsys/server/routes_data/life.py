"""生活域接口：事务箱 + 订阅卡片。

只做鉴权、参数校验与返回；SQL 在 `store/life_items.py` / `store/personal.py`，
状态机与提醒文案在 `services/life/`。
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import life as life_service
from .common import _conn

router = APIRouter()


class ItemBody(BaseModel):
    title: str = ""
    kind: str = "todo"
    due_date: str = ""
    note: str = ""
    value: str = ""


class ItemPatch(BaseModel):
    title: str | None = None
    kind: str | None = None
    due_date: str | None = None
    note: str | None = None
    value: str | None = None


class CardReadBody(BaseModel):
    read: bool = True


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _checked(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise _bad(str(exc)) from exc


# ------------------------------------------------------------------ 事务箱

@router.get("/api/life/items")
def list_items(status: str = "open", limit: int = 200,
               _=Depends(require_token)):
    if status and status != "all" and status not in store.LIFE_ITEM_STATUSES:
        raise _bad("状态只能是 open / done / archived / all")
    conn = _conn()
    try:
        items = store.list_life_items(conn, status=status, limit=limit)
        counts = store.life_item_counts(
            conn, dt.date.today().isoformat())
        return {"items": items, "count": len(items), "counts": counts}
    finally:
        conn.close()


@router.get("/api/life/items/{item_id}")
def get_item(item_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.get_life_item(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条事务")
        return item
    finally:
        conn.close()


@router.post("/api/life/items")
def add_item(body: ItemBody, _=Depends(require_token)):
    _checked(life_service.validate, body.kind, body.due_date)
    conn = _conn()
    try:
        return _checked(store.add_life_item, conn, title=body.title,
                        kind=body.kind, due_date=body.due_date,
                        note=body.note, value=body.value)
    finally:
        conn.close()


@router.patch("/api/life/items/{item_id}")
def update_item(item_id: int, body: ItemPatch, _=Depends(require_token)):
    changes = body.model_dump(exclude_none=True)
    if "kind" in changes or "due_date" in changes:
        _checked(life_service.validate, changes.get("kind", "todo"),
                 changes.get("due_date", ""))
    conn = _conn()
    try:
        item = _checked(store.update_life_item, conn, item_id, **changes)
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条事务")
        return item
    finally:
        conn.close()


def _change_status(item_id: int, target: str) -> dict:
    conn = _conn()
    try:
        item = _checked(life_service.change_status, conn, item_id, target)
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条事务")
        return item
    finally:
        conn.close()


@router.post("/api/life/items/{item_id}/done")
def done_item(item_id: int, _=Depends(require_token)):
    return _change_status(item_id, "done")


@router.post("/api/life/items/{item_id}/reopen")
def reopen_item(item_id: int, _=Depends(require_token)):
    return _change_status(item_id, "open")


@router.post("/api/life/items/{item_id}/archive")
def archive_item(item_id: int, _=Depends(require_token)):
    return _change_status(item_id, "archived")


@router.delete("/api/life/items/{item_id}")
def delete_item(item_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.delete_life_item(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条事务")
        return {"deleted": True, "id": int(item_id)}
    finally:
        conn.close()


# ---------------------------------------------------------------- 订阅卡片

@router.get("/api/life/cards")
def list_life_cards(day: str = "", limit: int = 50, _=Depends(require_token)):
    conn = _conn()
    try:
        if day:
            items = store.list_cards(conn, day=day, domain="life", limit=limit)
        else:
            items = store.list_recent_cards(conn, days=1, limit=limit)
        return {"items": items, "count": len(items)}
    finally:
        conn.close()


@router.post("/api/life/cards/{card_id}/read")
def read_life_card(card_id: int, body: CardReadBody,
                   _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.mark_read(conn, card_id, bool(body.read))
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这张卡片")
        return item
    finally:
        conn.close()
