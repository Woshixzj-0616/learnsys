"""Agent 接口包：对话、运行流水、会话。

对外仍用 `routes_agent.router`；测试常用的 `agent` / `_CONFIRM` / `_trace_event`
在这里原样转发，避免改测试。
"""
from __future__ import annotations

from fastapi import APIRouter

from learnsys import agent

from . import chat, conversations, deep, runs
from .chat import ChatRequest, ConfirmRequest, StopRequest
from .common import _clip, _load_history, _sse, _trace_event
from .state import (_ACTIVE, _ACTIVE_LOCK, _ACTIVE_RUNS, _CONFIRM, _CONFIRM_LOCK,
                    _TRACE_KINDS, CONFIRM_WAIT_SECONDS)

router = APIRouter()
router.include_router(chat.router)
router.include_router(deep.router)
router.include_router(runs.router)
router.include_router(conversations.router)

__all__ = [
    "router", "agent", "ChatRequest", "StopRequest", "ConfirmRequest",
    "_ACTIVE", "_ACTIVE_LOCK", "_ACTIVE_RUNS", "_CONFIRM", "_CONFIRM_LOCK",
    "CONFIRM_WAIT_SECONDS",
    "_TRACE_KINDS", "_sse", "_clip", "_trace_event", "_load_history",
]
