"""创作库接口：作品档案 + 风格预设 + 豆包文本导入 + 图片回显。

只做鉴权、校验与返回；SQL 在 `store/art.py`，路径安全与导入解析在
`services/life/art.py`。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import life as life_service
from .common import _conn

router = APIRouter()


class PresetBody(BaseModel):
    name: str = ""
    prompt: str = ""
    negative: str = ""
    note: str = ""


class PresetPatch(BaseModel):
    name: str | None = None
    prompt: str | None = None
    negative: str | None = None
    note: str | None = None


class WorkBody(BaseModel):
    title: str = ""
    prompt: str = ""
    preset_id: int = 0
    model: str = ""
    file_path: str = ""
    note: str = ""


class WorkPatch(BaseModel):
    title: str | None = None
    prompt: str | None = None
    preset_id: int | None = None
    model: str | None = None
    file_path: str | None = None
    note: str | None = None


class ImportBody(BaseModel):
    text: str = ""


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _checked(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise _bad(str(exc)) from exc


def _check_preset(conn, preset_id: int) -> None:
    if int(preset_id or 0) <= 0:
        return
    if store.get_art_preset(conn, preset_id) is None:
        raise _bad("找不到这个风格预设")


# ------------------------------------------------------------------ 风格预设

@router.get("/api/art/presets")
def list_presets(_=Depends(require_token)):
    conn = _conn()
    try:
        items = store.list_art_presets(conn)
        return {"items": items, "count": len(items)}
    finally:
        conn.close()


@router.post("/api/art/presets")
def save_preset(body: PresetBody, _=Depends(require_token)):
    conn = _conn()
    try:
        return _checked(store.upsert_art_preset, conn, name=body.name,
                        prompt=body.prompt, negative=body.negative,
                        note=body.note)
    finally:
        conn.close()


@router.patch("/api/art/presets/{preset_id}")
def update_preset(preset_id: int, body: PresetPatch,
                  _=Depends(require_token)):
    conn = _conn()
    try:
        item = _checked(store.update_art_preset, conn, preset_id,
                        **body.model_dump(exclude_none=True))
        if item is None:
            raise HTTPException(status_code=404, detail="找不到这个风格预设")
        return item
    finally:
        conn.close()


@router.delete("/api/art/presets/{preset_id}")
def delete_preset(preset_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.delete_art_preset(conn, preset_id)
        if item is None:
            raise HTTPException(status_code=404, detail="找不到这个风格预设")
        return {"deleted": True, "id": int(preset_id)}
    finally:
        conn.close()


# -------------------------------------------------------------------- 作品

@router.get("/api/art/works")
def list_works(status: str = "active", limit: int = 200,
               _=Depends(require_token)):
    if status and status != "all" and status not in store.ART_WORK_STATUSES:
        raise _bad("作品状态只能是 active / archived / all")
    conn = _conn()
    try:
        items = store.list_art_works(conn, status=status, limit=limit)
        return {"items": items, "count": len(items)}
    finally:
        conn.close()


@router.get("/api/art/works/{work_id}")
def get_work(work_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.get_art_work(conn, work_id)
        if item is None:
            raise HTTPException(status_code=404, detail="找不到这件作品")
        return item
    finally:
        conn.close()


@router.post("/api/art/works")
def add_work(body: WorkBody, _=Depends(require_token)):
    _checked(life_service.validate_work, body.title, body.file_path)
    conn = _conn()
    try:
        _check_preset(conn, body.preset_id)
        return _checked(store.add_art_work, conn, title=body.title,
                        prompt=body.prompt, preset_id=body.preset_id,
                        model=body.model, file_path=body.file_path,
                        note=body.note)
    finally:
        conn.close()


@router.patch("/api/art/works/{work_id}")
def update_work(work_id: int, body: WorkPatch, _=Depends(require_token)):
    changes = body.model_dump(exclude_none=True)
    conn = _conn()
    try:
        current = store.get_art_work(conn, work_id)
        if current is None:
            raise HTTPException(status_code=404, detail="找不到这件作品")
        if "title" in changes or "file_path" in changes:
            _checked(life_service.validate_work,
                     changes.get("title", current["title"]),
                     changes.get("file_path", current["file_path"]))
        if "preset_id" in changes:
            _check_preset(conn, changes["preset_id"])
        return _checked(store.update_art_work, conn, work_id, **changes)
    finally:
        conn.close()


@router.post("/api/art/works/{work_id}/archive")
def archive_work(work_id: int, _=Depends(require_token)):
    return _set_status(work_id, "archived")


@router.post("/api/art/works/{work_id}/restore")
def restore_work(work_id: int, _=Depends(require_token)):
    return _set_status(work_id, "active")


def _set_status(work_id: int, status: str) -> dict:
    conn = _conn()
    try:
        item = _checked(store.set_art_work_status, conn, work_id, status)
        if item is None:
            raise HTTPException(status_code=404, detail="找不到这件作品")
        return item
    finally:
        conn.close()


@router.delete("/api/art/works/{work_id}")
def delete_work(work_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.delete_art_work(conn, work_id)
        if item is None:
            raise HTTPException(status_code=404, detail="找不到这件作品")
        return {"deleted": True, "id": int(work_id)}
    finally:
        conn.close()


# -------------------------------------------------------------------- 导入

@router.post("/api/art/import")
def import_text(body: ImportBody, _=Depends(require_token)):
    conn = _conn()
    try:
        works = _checked(life_service.import_works, conn, body.text)
        return {"items": works, "count": len(works)}
    finally:
        conn.close()


# ---------------------------------------------------------------- 图片回显

@router.get("/media/art/{work_id}/image", include_in_schema=False)
def work_image(work_id: int):
    conn = _conn()
    try:
        work = store.get_art_work(conn, work_id)
    finally:
        conn.close()
    path = life_service.safe_image_path(work) if work else None
    if path is None:
        raise HTTPException(status_code=404, detail="这件作品没有可显示的图片")
    return FileResponse(path)
