"""Web 工作台的模块清单。

壳层只认这里返回的 `modules`：加模块 = 往 registry.json 里加一条，不改前端。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from learnsys.modules import load_registry
from learnsys.server.security import require_token

router = APIRouter()


@router.get("/api/modules")
def modules(_=Depends(require_token)):
    return load_registry()
