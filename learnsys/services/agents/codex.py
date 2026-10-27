"""Codex CLI 只读派活。

Codex 的模型走本机中转口（默认 `127.0.0.1:57321`）；中转口没开时 `codex exec`
会一直重连。这里提前探活，界面直接说「先打开 Codex」，不让任务空转。
"""
from __future__ import annotations

import pathlib
import shutil
import socket
import tomllib
import urllib.parse

from .base import AgentSpec


def _provider_base() -> str:
    path = pathlib.Path.home() / ".codex" / "config.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return ""
    name = str(data.get("model_provider") or "")
    providers = data.get("model_providers")
    if not isinstance(providers, dict):
        return ""
    provider = providers.get(name)
    if not isinstance(provider, dict):
        return ""
    return str(provider.get("base_url") or "")


def _local_port(base_url: str) -> int:
    try:
        parsed = urllib.parse.urlparse(base_url)
    except ValueError:
        return 0
    host = (parsed.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return 0
    try:
        return int(parsed.port or (443 if parsed.scheme == "https" else 80))
    except (TypeError, ValueError):
        return 0


def relay_note() -> str:
    """本地中转口没开时返回中文原因；远程或读不到配置就不拦。"""
    port = _local_port(_provider_base())
    if not port:
        return ""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return ""
    except OSError:
        return f"Codex 中转口未启动（127.0.0.1:{port}，先打开 Codex）"


def spec(settings: dict | None = None) -> AgentSpec:
    cfg = (settings or {}).get("codex")
    cfg = cfg if isinstance(cfg, dict) else {}
    enabled = cfg.get("enabled", True) is not False
    command = str(cfg.get("command") or "codex").strip()
    args = [str(item) for item in (cfg.get("args") or [])]
    found = shutil.which(command)
    note = ""
    if not enabled:
        note = "已停用"
    elif not found:
        note = "未安装 codex 命令"
    else:
        note = relay_note()
    return AgentSpec(
        id="codex", name="Codex CLI", kind="codex", command=found or command,
        args=args, available=bool(found) and enabled and not note,
        note=note,
    )
