"""本机可读目录的索引接口：看状态、立即重建。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from learnsys.server.security import require_token
from learnsys.services import local_index

router = APIRouter()


@router.get("/api/local-index")
def get_local_index(_=Depends(require_token)):
    return local_index.status()


@router.post("/api/local-index/rebuild")
def rebuild_local_index(_=Depends(require_token)):
    local_index.rebuild()
    return {"ok": True, "message": "已开始重建本机文件索引"}
