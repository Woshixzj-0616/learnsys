"""P26.2 Agent 中枢：只读派活 + 可写任务（写操作逐条审批）。"""
from __future__ import annotations

from . import approvals, queue, registry, route
from .base import AgentSpec, TaskEvent, build_argv, parse_line
from .registry import (approval_timeout, list_specs, max_concurrent, queue_max,
                       settings, spec_for, timeout)
from .runner import cancel_task, start_task
from .workspace import allowed_roots, default_workspace, resolve_workspace

__all__ = [
    "AgentSpec", "TaskEvent", "build_argv", "parse_line",
    "list_specs", "spec_for", "settings", "timeout", "max_concurrent",
    "queue_max", "approval_timeout", "approvals",
    "start_task", "cancel_task", "queue", "registry", "route",
    "allowed_roots", "default_workspace", "resolve_workspace",
]
