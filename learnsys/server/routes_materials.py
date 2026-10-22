"""资料库接口：上传/抽取、列表与检索、笔记、回收站、打开原文、导出 Markdown。

原文只存在数据目录的 `资料库/原文/`；正文存 `materials.body`，FTS 是派生索引。
上传走原始字节（不是 base64/multipart），前端直接把 File 当 body 发，省 33% 内存。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import subprocess
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from learnsys import config as app_config
from learnsys import store
from learnsys.ask import study
from learnsys.materials import search as material_search
from learnsys.services import materials_import
from learnsys.server.security import require_token

router = APIRouter()

MAX_BYTES = 50 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
DOC_SUFFIX = {".pdf", ".docx", ".pptx", ".txt", ".md"}


class NoteIn(BaseModel):
    title: str = Field(default="新的笔记", max_length=200)
    body: str = Field(default="", max_length=MAX_TEXT_CHARS)
    course: str = Field(default="", max_length=80)
    tags: str = Field(default="", max_length=200)


class ImportDirIn(BaseModel):
    path: str = Field(max_length=500)
    source: str = Field(default="courses", max_length=20)
    recursive: bool = True
    course: str = Field(default="", max_length=80)
    tags: str = Field(default="", max_length=200)


class MaterialUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    course: str | None = Field(default=None, max_length=80)
    tags: str | None = Field(default=None, max_length=200)


def _clean_name(name: str) -> str:
    name = pathlib.PurePath(str(name or "")).name
    name = re.sub(r"[\x00-\x1f]", "", name).strip()
    return name[:200] or "未命名资料"


def _suffix(name: str) -> str:
    match = re.search(r"(\.[A-Za-z0-9]{1,8})$", str(name or "").strip())
    return match.group(1).lower() if match else ""


def _resolve(rel: str) -> pathlib.Path | None:
    """数据库里的相对路径 → 绝对路径；只允许落在数据目录内。"""
    if not rel:
        return None
    root = pathlib.Path(app_config.DATA_ROOT).resolve()
    try:
        target = (root / rel).resolve()
        target.relative_to(root)
        return target
    except (OSError, ValueError):
        return None


def _save_markdown(item: dict) -> str:
    body = str(item.get("body") or "")
    if item.get("kind") == "pdf" and "\f" in body:
        body = "\n\n".join(
            f"--- 第 {index} 页 ---\n{page}"
            for index, page in enumerate(body.split("\f"), 1))
    meta = [f"类型：{item.get('kind') or ''}"]
    if item.get("course"):
        meta.append(f"课程：{item['course']}")
    if item.get("tags"):
        meta.append(f"标签：{item['tags']}")
    return f"# {item.get('title') or '未命名资料'}\n\n> " + " ｜ ".join(meta) + "\n\n" + body


@router.post("/api/materials/upload")
async def upload_material(request: Request, name: str = "", course: str = "",
                          tags: str = "", _=Depends(require_token)):
    """原始文件字节 → 原文落盘、正文入库。查重按 SHA256。"""
    original = _clean_name(name)
    course = str(course or "").strip()[:80]
    tags = str(tags or "").strip()[:200]
    suffix = _suffix(original)
    if suffix not in DOC_SUFFIX:
        raise HTTPException(status_code=400,
                            detail="资料只支持 pdf / docx / pptx / txt / md")
    blob = await request.body()
    if not blob:
        raise HTTPException(status_code=400, detail="上传内容为空")
    if len(blob) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 50MB，先压小一点再传")

    raw_dir = pathlib.Path(app_config.materials_dir()) / "原文"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stored = raw_dir / f"{uuid.uuid4().hex[:16]}{suffix}"
    await run_in_threadpool(stored.write_bytes, blob)
    try:
        extracted = await run_in_threadpool(study.extract_document, str(stored))
    except Exception as exc:
        stored.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"读文档失败：{exc}") from exc

    text = str(extracted.get("text") or "").strip()
    if len(text) < 20:
        stored.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="这份文档几乎没读到文字（扫描版 PDF 需要先 OCR），换一份试试")

    truncated = len(text) > MAX_TEXT_CHARS
    if truncated:
        text = text[:MAX_TEXT_CHARS]
    sha256 = hashlib.sha256(blob).hexdigest()
    rel_path = stored.relative_to(pathlib.Path(app_config.DATA_ROOT)).as_posix()
    conn = store.connect()
    try:
        item_id, created = store.add_material(
            conn, title=original, kind=extracted.get("kind") or suffix[1:],
            source="upload", path=rel_path, body=text,
            pages=int(extracted.get("pages") or 0), size=len(blob), sha256=sha256,
            course=course, tags=tags,
            meta={"original_name": original, "truncated": truncated})
        if not created:
            stored.unlink(missing_ok=True)      # 同一份文件：保留已有原文
        item = store.get_material(conn, item_id, with_body=False)
        return {"ok": True, "created": created, "item": item}
    except Exception:
        stored.unlink(missing_ok=True)          # 入库失败不留孤儿原文
        raise
    finally:
        conn.close()


@router.post("/api/materials/import-dir")
def import_materials_dir(req: ImportDirIn, _=Depends(require_token)):
    """批量导入一个目录：设置里的白名单，按 SHA256 去重；不移动原文件。"""
    try:
        return materials_import.import_dir(
            req.path, source=req.source, recursive=req.recursive,
            course=req.course.strip(), tags=req.tags.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/materials/note")
def create_note(req: NoteIn, _=Depends(require_token)):
    conn = store.connect()
    try:
        item_id, created = store.add_material(
            conn, title=req.title, kind="note", source="note", body=req.body,
            course=req.course, tags=req.tags)
        return {"ok": True, "created": created,
                "item": store.get_material(conn, item_id)}
    finally:
        conn.close()


@router.get("/api/materials")
def list_materials(q: str = "", kind: str = "", course: str = "",
                   status: str = "active", limit: int = 200,
                   _=Depends(require_token)):
    conn = store.connect()
    try:
        q = q.strip()
        if q:
            hits = material_search.search(conn, q, limit=max(1, min(limit, 50)))
            items = []
            for hit in hits:
                item = store.get_material(conn, hit["material_id"], with_body=False)
                if item is None:
                    continue
                if status in ("active", "trashed") and item["status"] != status:
                    continue
                if kind and item["kind"] != kind:
                    continue
                if course and item["course"] != course:
                    continue
                item.update({"snippet": hit["snippet"], "page": hit["page"],
                             "score": hit["score"]})
                items.append(item)
            return {"query": q, "items": items, "counts": store.material_counts(conn)}
        items = store.list_materials(conn, kind=kind, course=course,
                                     status=status, limit=limit)
        return {"query": "", "items": items, "counts": store.material_counts(conn)}
    finally:
        conn.close()


@router.get("/api/materials/{item_id}")
def get_material(item_id: int, body: int = 1, _=Depends(require_token)):
    conn = store.connect()
    try:
        item = store.get_material(conn, item_id, with_body=bool(body))
        if item is None:
            raise HTTPException(status_code=404, detail="这份资料不在了")
        return {"item": item}
    finally:
        conn.close()


@router.get("/api/materials/{item_id}/quiz-prompt")
def material_quiz_prompt(item_id: int, _=Depends(require_token)):
    """从一份资料出题的提示词；正文按页截前 12000 字，其余交给 read_material。"""
    conn = store.connect()
    try:
        item = store.get_material(conn, item_id)
        if item is None or item.get("status") != "active":
            raise HTTPException(status_code=404, detail="这份资料不在了")
        prompt = study.build_material_quiz_question(item)
        store.touch_material(conn, item_id)
        meta = store.get_material(conn, item_id, with_body=False)
        return {"material": meta, "prompt": prompt}
    finally:
        conn.close()


@router.post("/api/materials/{item_id}")
def update_material(item_id: int, req: MaterialUpdateIn, _=Depends(require_token)):
    conn = store.connect()
    try:
        current = store.get_material(conn, item_id)
        if current is None:
            raise HTTPException(status_code=404, detail="这份资料不在了")
        body = req.body if current["kind"] == "note" else None
        item = store.update_material(
            conn, item_id, title=req.title, body=body,
            course=req.course, tags=req.tags)
        return {"ok": True, "item": item}
    finally:
        conn.close()


@router.post("/api/materials/{item_id}/trash")
def trash_material(item_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        item = store.get_material(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="这份资料不在了")
        source = _resolve(item["path"])
        if source is not None and source.exists():
            trash_dir = pathlib.Path(app_config.materials_dir()) / "回收站"
            trash_dir.mkdir(parents=True, exist_ok=True)
            target = trash_dir / source.name
            if target.exists():
                target = trash_dir / f"{source.stem}-{uuid.uuid4().hex[:6]}{source.suffix}"
            try:
                source.rename(target)
                rel = target.relative_to(pathlib.Path(app_config.DATA_ROOT)).as_posix()
                conn.execute("UPDATE materials SET path = ? WHERE id = ?", (rel, item_id))
                conn.commit()
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"原文移不进回收站：{exc}") from exc
        store.set_material_status(conn, item_id, "trashed")
        return {"ok": True, "id": item_id}
    finally:
        conn.close()


@router.post("/api/materials/{item_id}/restore")
def restore_material(item_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        item = store.get_material(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="这份资料不在了")
        source = _resolve(item["path"])
        if source is not None and source.exists():
            raw_dir = pathlib.Path(app_config.materials_dir()) / "原文"
            raw_dir.mkdir(parents=True, exist_ok=True)
            target = raw_dir / source.name
            if target.exists():
                target = raw_dir / f"{source.stem}-{uuid.uuid4().hex[:6]}{source.suffix}"
            try:
                source.rename(target)
                rel = target.relative_to(pathlib.Path(app_config.DATA_ROOT)).as_posix()
                conn.execute("UPDATE materials SET path = ? WHERE id = ?", (rel, item_id))
                conn.commit()
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"原文移不回原文目录：{exc}") from exc
        store.set_material_status(conn, item_id, "active")
        return {"ok": True, "item": store.get_material(conn, item_id, with_body=False)}
    finally:
        conn.close()


@router.delete("/api/materials/{item_id}")
def delete_material(item_id: int, _=Depends(require_token)):
    """彻底删除：只允许删回收站里的，原文和记录一起清掉。"""
    conn = store.connect()
    try:
        item = store.get_material(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="这份资料不在了")
        if item["status"] != "trashed":
            raise HTTPException(status_code=409, detail="先移进回收站，再彻底删除")
        source = _resolve(item["path"])
        if source is not None and source.exists():
            try:
                source.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"删原文失败：{exc}") from exc
        store.delete_material_row(conn, item_id)
        return {"ok": True, "id": item_id}
    finally:
        conn.close()


@router.post("/api/materials/{item_id}/open")
def open_material(item_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        item = store.get_material(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="这份资料不在了")
        path = _resolve(item["path"])
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="原文文件不在了（笔记没有原文）")
        store.touch_material(conn, item_id)
        store.add_event(conn, "materials", "open", item["title"],
                        {"material_id": item_id})
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))       # noqa: S606 —— 本地用户自己的文件
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"打不开原文：{exc}") from exc
        return {"ok": True}
    finally:
        conn.close()


@router.get("/api/materials/{item_id}/export")
def export_material(item_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        item = store.get_material(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="这份资料不在了")
        text = _save_markdown(item)
        store.touch_material(conn, item_id)
    finally:
        conn.close()
    base = item["title"] or "资料"
    if item.get("kind") != "note" and "." in base:
        base = base.rsplit(".", 1)[0]
    filename = f"{base or '资料'}.md"
    return Response(
        content=text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{quote(filename, safe='')}"})
