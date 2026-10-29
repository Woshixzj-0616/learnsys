"""复习卡「运行代码」：薄转接沙箱，不复制执行逻辑。

沙箱本身的能力边界（禁网、超时、内存、临时目录）见 `learnsys/agent/sandbox.py`。
这里只做令牌校验、参数上下限与结果转 dict；任何执行参数都不要在路由里重写。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from learnsys.agent import sandbox
from learnsys.server.security import require_token

router = APIRouter()


class CodeRunIn(BaseModel):
    language: str = Field(default="", description="cpp / c / python；空=按代码推断")
    code: str = Field(min_length=1, max_length=sandbox.MAX_CODE_BYTES)
    stdin: str = Field(default="", max_length=10_000)


@router.post("/api/code/run")
def run_code(req: CodeRunIn, _=Depends(require_token)):
    result = sandbox.run(req.language, req.code, stdin_text=req.stdin)
    return {
        "ok": result.ok,
        "language": result.language,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
        "note": result.note,
    }
