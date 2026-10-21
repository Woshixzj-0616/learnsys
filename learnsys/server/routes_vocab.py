"""P13 生词接口：统一表 `vocab_items` 的读写与导出。"""
from __future__ import annotations

import csv
import io
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token

router = APIRouter()


class VocabIn(BaseModel):
    word: str = Field(min_length=1, max_length=200)
    meaning: str = ""
    phonetic: str = ""
    context: str = ""
    paper_id: str = ""
    paper_title: str = ""
    sentence: int = 0
    source: str = "cet6"


class VocabPatch(BaseModel):
    meaning: str | None = None
    phonetic: str | None = None
    status: str | None = None


class VocabImport(BaseModel):
    items: list[dict] = Field(default_factory=list)


@router.get("/api/vocab")
def list_vocab(query: str = "", limit: int = 200, offset: int = 0,
               status: str = "active", _=Depends(require_token)):
    conn = store.connect()
    try:
        return store.list_vocab(conn, query=query, limit=limit, offset=offset,
                                status=status)
    finally:
        conn.close()


@router.post("/api/vocab")
def add_vocab(req: VocabIn, _=Depends(require_token)):
    conn = store.connect()
    try:
        item, created = store.add_vocab(
            conn, word=req.word, meaning=req.meaning, phonetic=req.phonetic,
            context=req.context, paper_id=req.paper_id,
            paper_title=req.paper_title, sentence=req.sentence, source=req.source)
        return {"item": item, "created": created}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.patch("/api/vocab/{item_id}")
def patch_vocab(item_id: int, req: VocabPatch, _=Depends(require_token)):
    conn = store.connect()
    try:
        try:
            item = store.update_vocab(conn, item_id, **req.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=404, detail="生词不存在")
        return {"item": item}
    finally:
        conn.close()


@router.delete("/api/vocab/{item_id}")
def remove_vocab(item_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        if not store.delete_vocab(conn, item_id):
            raise HTTPException(status_code=404, detail="生词不存在")
        return {"ok": True, "id": item_id}
    finally:
        conn.close()


@router.post("/api/vocab/import")
def import_vocab(req: VocabImport, _=Depends(require_token)):
    conn = store.connect()
    try:
        return store.import_vocab(conn, req.items)
    finally:
        conn.close()


@router.get("/api/vocab/export.csv")
def export_vocab(_=Depends(require_token)):
    conn = store.connect()
    try:
        rows = store.export_vocab(conn)
    finally:
        conn.close()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["单词", "释义", "音标", "上下文", "试卷", "加入时间"])
    for item in rows:
        writer.writerow([item["word"], item["meaning"], item["phonetic"],
                         item["context"], item["paper_title"], item["created_at"]])
    name = urllib.parse.quote("生词本.csv")
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})
