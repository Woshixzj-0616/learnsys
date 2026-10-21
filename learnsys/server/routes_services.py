"""P13 服务目录接口：列出可用服务并按 kind 分派。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from learnsys.server.security import require_token
from learnsys.services import catalog

router = APIRouter()


@router.get("/api/services")
def list_services(_=Depends(require_token)):
    return catalog.catalog()


@router.post("/api/services/{kind}")
def run_service(kind: str, payload: dict | None = Body(default=None),
                _=Depends(require_token)):
    try:
        result, mode = catalog.dispatch(kind, payload)
    except catalog.UnknownService as exc:
        raise HTTPException(status_code=404, detail=f"没有这个服务：{exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"服务执行失败：{exc}") from exc
    if mode == "job":
        return JSONResponse(status_code=202, content=result)
    return result
