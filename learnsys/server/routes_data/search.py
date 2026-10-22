"""跨天检索：FTS / LIKE 的统一入口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from learnsys.core import db as core_db
from learnsys.server.security import require_token
from .common import _conn

router = APIRouter()


@router.get("/api/search")
def search(q: str = "", limit: int = 20, _=Depends(require_token)):
    if not q.strip():
        return {"query": q, "results": []}
    conn = _conn()
    try:
        return {"query": q, "results": core_db.search(conn, q, limit=limit)}
    finally:
        conn.close()
