"""Claude Code 只读派活：命令探测 + 规格。argv / 解析在 base.py。"""
from __future__ import annotations

import shutil

from .base import AgentSpec


def spec(settings: dict | None = None) -> AgentSpec:
    cfg = (settings or {}).get("claude")
    cfg = cfg if isinstance(cfg, dict) else {}
    enabled = cfg.get("enabled", True) is not False
    command = str(cfg.get("command") or "claude").strip()
    args = [str(item) for item in (cfg.get("args") or [])]
    found = shutil.which(command)
    return AgentSpec(
        id="claude", name="Claude Code", kind="claude", command=found or command,
        args=args, available=bool(found) and enabled,
        note="" if found and enabled else ("已停用" if not enabled else "未安装 claude 命令"),
    )
