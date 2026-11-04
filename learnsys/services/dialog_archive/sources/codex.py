"""Codex 会话：只收 response_item.message 里的 user/assistant 正文。"""
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

ROOT = pathlib.Path.home() / ".codex" / "sessions"


def collect(cutoff_ts: float) -> dict:
    files = [path for path in glob_files(ROOT, "**/rollout-*.jsonl")
             if before_cutoff(path, cutoff_ts)]
    sessions: list[Session] = []
    skipped = 0
    errors = [0]
    for path in files:
        session_id = path.stem
        messages: list[Message] = []
        for item in iter_jsonl(path, errors):
            kind = item.get("type")
            payload = item.get("payload") or {}
            if kind == "session_meta":
                session_id = str(payload.get("session_id") or session_id)
                continue
            if kind != "response_item":
                continue
            if payload.get("type") != "message":
                skipped += 1
                continue
            role = payload.get("role")
            if role not in ("user", "assistant"):
                skipped += 1
                continue
            text = clean_text(content_text(payload.get("content")))
            if not text or (role == "user" and is_injected(text)):
                skipped += 1
                continue
            messages.append(Message(role, text, str(item.get("timestamp") or "")))
        if messages:
            sessions.append(Session(
                source="codex", session_id=session_id,
                title=messages[0].text[:60].replace("\n", " "),
                at=file_time(path), path=str(path), messages=messages))
    return {"files": len(files), "sessions": sessions,
            "skipped": skipped, "errors": errors[0]}


SOURCE = Source("codex", "Codex", "A", collect)
