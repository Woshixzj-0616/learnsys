"""会话列表与历史消息。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from learnsys import store
from learnsys.server.security import require_token

router = APIRouter()


@router.get("/api/conversations")
def conversations(limit: int = 20, module: str = "ask", _=Depends(require_token)):
    conn = store.connect()
    try:
        return {"items": store.list_conversations(
            conn, limit=limit, module="" if module == "all" else module)}
    finally:
        conn.close()


@router.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        row = store.get_conversation(conn, conversation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = store.conversation_messages(conn, conversation_id)
        return {
            "id": row[0], "title": row[1] or "", "module": row[2] or "ask",
            "mode": row[3] or "explain", "summary": row[4] or "",
            "started_at": row[5] or "", "updated_at": row[6] or "",
            "messages": messages,
        }
    finally:
        conn.close()
