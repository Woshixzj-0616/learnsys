"""长期记忆接口：设置页看 / 改 / 删，Agent 工具走同一张表。

原则：只有一个落点 —— `agent_memories` 表。这里不做第二份文本文件，
否则「工具记的」和「界面改的」迟早对不上。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.services import profile_view
from learnsys.server.security import require_token

router = APIRouter()


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    kind: str = "preference"
    scope: str = "global"
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    evidence: str = ""
    pinned: bool = False


@router.get("/api/memory")
def list_memory(status: str = "active", kind: str = "", scope: str = "",
                limit: int = Query(200, ge=1, le=1000),
                _=Depends(require_token)):
    conn = store.connect()
    try:
        items = store.list_memories(
            conn, limit=limit, include_archived=(status == "all"),
            status="" if status in ("all", "") else status,
            kinds=(kind,) if kind else (), scope=scope)
        return {"items": items}
    finally:
        conn.close()


@router.post("/api/memory")
def add_memory(req: MemoryIn, _=Depends(require_token)):
    conn = store.connect()
    try:
        memory_id, created = store.add_memory(
            conn, req.content, req.kind, scope=req.scope,
            evidence=req.evidence, confidence=req.confidence,
            source="profile_api", pinned=1 if req.pinned else 0)
        return {"ok": True, "id": memory_id, "created": created,
                "message": "已记住，下一轮对话生效" if created else "这条已经在记忆里"}
    finally:
        conn.close()


@router.post("/api/memory/{memory_id}")
def update_memory(memory_id: int, req: MemoryIn, _=Depends(require_token)):
    conn = store.connect()
    try:
        if not store.update_memory(
                conn, memory_id, req.content, kind=req.kind, scope=req.scope,
                evidence=req.evidence, confidence=req.confidence,
                pinned=1 if req.pinned else 0):
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


@router.post("/api/memory/{memory_id}/promote")
def promote_memory(memory_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        if not store.promote_memory(conn, memory_id):
            raise HTTPException(status_code=404, detail="这条记忆不存在")
        return {"ok": True, "message": "已采纳为长期记忆"}
    finally:
        conn.close()


@router.post("/api/memory/{memory_id}/archive")
def archive_memory(memory_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        if not store.delete_memory(conn, memory_id, reason="user_archived"):
            raise HTTPException(status_code=404, detail="这条记忆不存在")
        return {"ok": True, "message": "已归档"}
    finally:
        conn.close()


@router.get("/api/memory/candidates")
def list_candidates(limit: int = Query(100, ge=1, le=500),
                    _=Depends(require_token)):
    conn = store.connect()
    try:
        return {"items": store.list_memories(
            conn, limit=limit, status="candidate")}
    finally:
        conn.close()


@router.get("/api/memory/profile")
def read_profile(_=Depends(require_token)):
    from learnsys import config
    conn = store.connect()
    try:
        stale = profile_view.profile_is_stale(conn, config.DATA_ROOT)
    except Exception:
        stale = True
    finally:
        conn.close()
    return {"text": profile_view.read_profile(config.DATA_ROOT),
            "stale": stale}


@router.post("/api/memory/profile/compile")
def compile_profile(_=Depends(require_token)):
    from learnsys import config
    return profile_view.compile_profile(config.DATA_ROOT)


@router.get("/api/memory/injections")
def memory_injections(limit: int = Query(10, ge=1, le=50),
                      _=Depends(require_token)):
    conn = store.connect()
    try:
        return {"items": store.recent_memory_injections(conn, limit=limit)}
    finally:
        conn.close()
