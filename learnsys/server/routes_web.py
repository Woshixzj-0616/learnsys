"""Web 工作台的插件清单。

壳层只认这里返回的 `modules`：加插件 = 新建 `learnsys/plugins/<id>/plugin.json`，
不改前端。`/api/plugins` 是同一份数据的语义化别名。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from learnsys.modules import load_registry
from learnsys.server.security import require_token

router = APIRouter()


@router.get("/api/modules")
def modules(_=Depends(require_token)):
    return load_registry()


@router.get("/api/plugins")
def plugins(_=Depends(require_token)):
    return load_registry()
