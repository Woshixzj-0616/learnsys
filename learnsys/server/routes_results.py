"""P13 结果资产接口：按 id / 条件读取 `service_results`。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import results

router = APIRouter()


@router.get("/api/results")
def list_results(kind: str = "", target_type: str = "", target_id: str = "",
                 scope: str = "", limit: int = 50, _=Depends(require_token)):
    conn = store.connect()
    try:
        return results.list_results(
            conn, kind=kind, target_type=target_type, target_id=target_id,
            scope=scope, limit=limit)
    finally:
        conn.close()


@router.get("/api/results/{result_id}")
def get_result(result_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        row = results.get(conn, result_id)
        if not row:
            raise HTTPException(status_code=404, detail="结果不存在")
        return results.to_public(row)
    finally:
        conn.close()
