"""P26.1 Agent 中枢：本机 agent 只读派活。"""
from __future__ import annotations

from .base import AgentSpec, TaskEvent, build_argv, parse_line
from .registry import (list_specs, max_concurrent, settings, spec_for, timeout)
from .runner import cancel_task, start_task
from .workspace import allowed_roots, default_workspace, resolve_workspace

__all__ = [
    "AgentSpec", "TaskEvent", "build_argv", "parse_line",
    "list_specs", "spec_for", "settings", "timeout", "max_concurrent",
    "start_task", "cancel_task",
    "allowed_roots", "default_workspace", "resolve_workspace",
]
