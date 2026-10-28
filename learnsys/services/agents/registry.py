"""本机 agent 探测与设置读取。"""
from __future__ import annotations

import subprocess
import time

from learnsys import config as app_config

from . import claude, codex
from .base import AgentSpec

_VERSION_CACHE: dict[str, tuple[float, str]] = {}
_VERSION_TTL = 60.0


def settings() -> dict:
    raw = app_config.USER.get("agents") if isinstance(app_config.USER, dict) else None
    return raw if isinstance(raw, dict) else {}


def timeout(settings_: dict | None = None) -> int:
    raw = (settings_ or settings()).get("timeout") or 300
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 300
    return max(10, min(value, 900))


def max_concurrent(settings_: dict | None = None) -> int:
    raw = (settings_ or settings()).get("max_concurrent") or 2
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 2
    return max(1, min(value, 4))


def queue_max(settings_: dict | None = None) -> int:
    """最多允许多少个任务排队（默认 10，1–100）。"""
    raw = (settings_ or settings()).get("queue_max") or 10
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 10
    return max(1, min(value, 100))


def approval_timeout(settings_: dict | None = None) -> int:
    """一条写操作等用户确认多久；到点按拒绝处理。"""
    raw = (settings_ or settings()).get("approval_timeout") or 110
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 110
    return max(10, min(value, 600))


def _probe_version(spec: AgentSpec) -> str:
    if not spec.available:
        return ""
    now = time.monotonic()
    cached = _VERSION_CACHE.get(spec.command)
    if cached and now - cached[0] < _VERSION_TTL:
        return cached[1]
    version = ""
    try:
        completed = subprocess.run(
            [spec.command, "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = (completed.stdout or completed.stderr or "").strip().splitlines()[0]
        version = line.split(" (")[0][:120]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        version = ""
    _VERSION_CACHE[spec.command] = (now, version)
    return version


def list_specs(settings_: dict | None = None) -> list[AgentSpec]:
    current = settings_ if settings_ is not None else settings()
    specs = [claude.spec(current), codex.spec(current)]
    for spec in specs:
        spec.version = _probe_version(spec)
    return specs


def spec_for(agent_id: str, settings_: dict | None = None) -> AgentSpec | None:
    wanted = str(agent_id or "").strip().lower()
    for spec in list_specs(settings_):
        if spec.id == wanted:
            return spec
    return None
