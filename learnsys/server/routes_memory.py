"""长期记忆接口：设置页看 / 改 / 删，Agent 工具走同一张表。

原则：只有一个落点 —— `agent_memories` 表。这里不做第二份文本文件，
否则「工具记的」和「界面改的」迟早对不上。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token

router = APIRouter()


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    kind: str = "preference"


@router.get("/api/memory")
def list_memory(_=Depends(require_token)):
    conn = store.connect()
    try:
        return {"items": store.list_memories(conn, limit=100)}
    finally:
        conn.close()


@router.post("/api/memory")
def add_memory(req: MemoryIn, _=Depends(require_token)):
    conn = store.connect()
    try:
        memory_id, created = store.add_memory(conn, req.content, kind=req.kind)
        return {"ok": True, "id": memory_id, "created": created,
                "message": "已记住，下一轮对话生效" if created else "这条已经在记忆里"}
    finally:
        conn.close()


@router.post("/api/memory/{memory_id}")
def update_memory(memory_id: int, req: MemoryIn, _=Depends(require_token)):
    conn = store.connect()
    try:
        if not store.update_memory(conn, memory_id, req.content):
            raise HTTPException(status_code=404, detail="这条记忆不存在或已删除")
        return {"ok": True, "message": "已更新"}
    finally:
        conn.close()


@router.delete("/api/memory/{memory_id}")
def delete_memory(memory_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        if not store.delete_memory(conn, memory_id):
            raise HTTPException(status_code=404, detail="这条记忆不存在或已删除")
        return {"ok": True, "message": "已忘掉"}
    finally:
        conn.close()
