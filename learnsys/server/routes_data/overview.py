"""学习台概览：路由只做鉴权与返回，口径在 `services/overview.py`。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from learnsys.server.security import require_token
from learnsys.services import overview as overview_service
from .common import _conn

router = APIRouter()


@router.get("/api/overview")
def overview(_=Depends(require_token)):
    conn = _conn()
    try:
        return overview_service.build(conn)
    finally:
        conn.close()
