"""数据接口包：今日、概览、事件、检索、错题本、六级上下文。

各子路由自带 `router`，这里只做聚合；调用方仍 `include_router(routes_data.router)`。
"""
from __future__ import annotations

from fastapi import APIRouter

from . import (art, cet6_context, events, home, life, overview, search, today,
               wrongbook)
from .common import _ask_dict, _conn

router = APIRouter()
router.include_router(home.router)
router.include_router(life.router)
router.include_router(art.router)
router.include_router(today.router)
router.include_router(overview.router)
router.include_router(events.router)
router.include_router(search.router)
router.include_router(wrongbook.router)
router.include_router(cet6_context.router)

__all__ = ["router", "_conn", "_ask_dict"]
