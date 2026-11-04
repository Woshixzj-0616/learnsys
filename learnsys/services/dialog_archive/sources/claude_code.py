"""Claude Code 会话：只收带 text 块的消息，排除工具结果与侧链。

注意：不能按 `origin.kind=human` 筛 —— 实测 30,790 条里只有 244 条带这个值，
绝大多数真人消息没有 origin 字段。正确判据是「有没有可读 text」。
"""
from __future__ import annotations

import pathlib

from ..model import Message, Session, Source
from .common import (
    before_cutoff,
    clean_text,
    content_text,
    file_time,
    glob_files,
    is_injected,
    iter_jsonl,
)

ROOT = pathlib.Path("D:/claude-code/config/projects")


def collect(cutoff_ts: float) -> dict:
    files = [path for path in glob_files(ROOT, "**/*.jsonl")
             if before_cutoff(path, cutoff_ts) and "subagents" not in path.parts]
    sessions: list[Session] = []
    skipped = 0
    errors = [0]
    for path in files:
        session_id = path.stem
        messages: list[Message] = []
        for item in iter_jsonl(path, errors):
            kind = item.get("type")
            if kind not in ("user", "assistant"):
                continue
            if item.get("isSidechain"):
                skipped += 1
                continue
            message = item.get("message") or {}
            session_id = str(item.get("sessionId") or session_id)
            role = message.get("role") or kind
            if role not in ("user", "assistant"):
                skipped += 1
                continue
            text = clean_text(content_text(message.get("content")))
            if not text or (role == "user" and is_injected(text)):
                skipped += 1
                continue
            messages.append(Message(role, text, str(item.get("timestamp") or "")))
        if messages:
            sessions.append(Session(
                source="claude_code", session_id=session_id,
                title=messages[0].text[:60].replace("\n", " "),
                at=file_time(path), path=str(path), messages=messages))
    return {"files": len(files), "sessions": sessions,
            "skipped": skipped, "errors": errors[0]}


SOURCE = Source("claude_code", "Claude Code", "B", collect)
