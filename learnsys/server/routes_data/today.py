"""今日页与配置：路由只做鉴权与返回，数据装配在 `services/today.py`。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from learnsys.llm.config import load_config
from learnsys.server.security import require_token
from learnsys.services import today as today_service
from learnsys.services import workbench as workbench_service
from .common import _conn

router = APIRouter()


@router.get("/api/config")
def get_config(_=Depends(require_token)):
    return load_config().public()


@router.get("/api/today")
def today(_=Depends(require_token)):
    conn = _conn()
    try:
        return today_service.payload(conn)
    finally:
        conn.close()


@router.get("/api/workbench")
def workbench(_=Depends(require_token)):
    """今日页一次取齐：概览 + 今日 + 三域，今日目标只算一遍。"""
    conn = _conn()
    try:
        return workbench_service.payload(conn)
    finally:
        conn.close()


@router.get("/api/study/today")
def study_today(focus: str = "", _=Depends(require_token)):
    conn = _conn()
    try:
        return today_service.study_payload(conn, focus=focus)
    finally:
        conn.close()
