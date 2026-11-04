"""Qwen Code 会话：只收 real_user 的 user 与 assistant 文本。"""
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

ROOT = pathlib.Path.home() / ".qwen" / "projects"


def collect(cutoff_ts: float) -> dict:
    files = [path for path in glob_files(ROOT, "**/chats/*.jsonl")
             if before_cutoff(path, cutoff_ts)]
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
            message = item.get("message") or {}
            role = message.get("role") or kind
            provenance = item.get("provenance")
            origin = provenance.get("kind") if isinstance(provenance, dict) else None
            if role == "user" and origin not in ("real_user", None):
                skipped += 1
                continue
            text = clean_text(content_text(message.get("parts") or []))
            if not text or (role == "user" and is_injected(text)):
                skipped += 1
                continue
            messages.append(Message(role, text, str(item.get("timestamp") or "")))
        if messages:
            sessions.append(Session(
                source="qwen", session_id=session_id,
                title=messages[0].text[:60].replace("\n", " "),
                at=file_time(path), path=str(path), messages=messages))
    return {"files": len(files), "sessions": sessions,
            "skipped": skipped, "errors": errors[0]}


SOURCE = Source("qwen", "Qwen Code", "D", collect)
