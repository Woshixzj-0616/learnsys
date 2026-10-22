"""深度分析接口：显式触发，只读，不混进主对话。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys.agent import deep
from learnsys.server.security import require_token

router = APIRouter()


class DeepIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    context: str = Field(default="", max_length=8000)


@router.get("/api/agent/deep")
def deep_status(_=Depends(require_token)):
    """界面用：能不能用、走命令还是 API、模型是谁（不返回密钥）。"""
    return deep.describe()


@router.post("/api/agent/deep")
def deep_run(req: DeepIn, _=Depends(require_token)):
    try:
        return deep.run(req.prompt, req.context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # 未启用 / 超时 / 命令不存在 / 没有输出，都是配置或运行问题
        raise HTTPException(status_code=409, detail=str(exc)) from exc
