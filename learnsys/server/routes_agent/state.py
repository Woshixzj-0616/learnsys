"""运行中的对话与写操作确认槽。

这些字典必须全进程一份：包级同名符号只是转发，测试可以直接读写。
"""
from __future__ import annotations

import threading


_ACTIVE: dict[str, threading.Event] = {}
_ACTIVE_LOCK = threading.Lock()

# 写操作确认：key = "run_id:request_id"；等用户点「允许 / 拒绝」或超时。
_CONFIRM: dict[str, dict] = {}
_CONFIRM_LOCK = threading.Lock()
CONFIRM_WAIT_SECONDS = 120

_TRACE_KINDS = {"plan", "plan_update", "tool_start", "tool_end", "confirm",
                "check", "rewrite", "activity", "error", "route"}
