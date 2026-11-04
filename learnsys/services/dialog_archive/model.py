"""对话总汇的数据结构：来源、会话、消息。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str          # user / assistant
    text: str
    at: str = ""       # ISO 时间，可为空


@dataclass
class Session:
    source: str
    session_id: str
    title: str = ""
    at: str = ""
    path: str = ""
    messages: list[Message] = field(default_factory=list)
    skipped: int = 0
    error: str = ""


@dataclass
class Source:
    id: str
    label: str
    section: str
    collect: Callable
    missing_reason: str = ""
