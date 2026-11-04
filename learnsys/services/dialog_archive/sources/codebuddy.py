"""CodeBuddy 会话：type=message 的 user/assistant 文本。"""
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

ROOT = pathlib.Path.home() / ".codebuddy" / "projects"


def collect(cutoff_ts: float) -> dict:
    files = [path for path in glob_files(ROOT, "**/*.jsonl")
             if before_cutoff(path, cutoff_ts)]
    sessions: list[Session] = []
    skipped = 0
    errors = [0]
    for path in files:
        session_id = path.stem
        messages: list[Message] = []
        for item in iter_jsonl(path, errors):
            if item.get("type") != "message":
                continue
            role = item.get("role")
            if role not in ("user", "assistant"):
                skipped += 1
                continue
            text = clean_text(content_text(item.get("content")))
            if not text or (role == "user" and is_injected(text)):
                skipped += 1
                continue
            messages.append(Message(role, text, str(item.get("timestamp") or "")))
            session_id = str(item.get("sessionId") or session_id)
        if messages:
            sessions.append(Session(
                source="codebuddy", session_id=session_id,
                title=messages[0].text[:60].replace("\n", " "),
                at=file_time(path), path=str(path), messages=messages))
    return {"files": len(files), "sessions": sessions,
            "skipped": skipped, "errors": errors[0]}


SOURCE = Source("codebuddy", "CodeBuddy", "E", collect)
