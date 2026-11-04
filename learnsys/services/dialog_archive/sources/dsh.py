"""DeepSeek Harness（DSH）：zstd 压缩的会话事件流。"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

from ..model import Message, Session, Source
from .common import before_cutoff, clean_text, content_text, is_injected

try:  # Python 3.14+ 标准库
    from compression import zstd  # type: ignore
except Exception:  # pragma: no cover - 旧环境没有 zstd
    zstd = None

ROOT = pathlib.Path.home() / ".dsh" / "sessions"


def _iso(value) -> str:
    if isinstance(value, dict):
        value = value.get("created") or value.get("start") or value.get("time")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if number > 10_000_000_000:
        number /= 1000.0
    try:
        return dt.datetime.fromtimestamp(number).strftime("%Y-%m-%dT%H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return ""


def _events(path: pathlib.Path, errors: list[int]):
    if zstd is None:
        errors[0] += 1
        return
    try:
        raw = zstd.decompress(path.read_bytes())
    except Exception:
        errors[0] += 1
        return
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            errors[0] += 1


def collect(cutoff_ts: float) -> dict:
    try:
        files = sorted(path for path in ROOT.glob("**/*.zstd")
                       if path.is_file() and before_cutoff(path, cutoff_ts))
    except OSError:
        files = []
    sessions: list[Session] = []
    skipped = 0
    errors = [0]
    for path in files:
        session_id = path.stem
        messages: list[Message] = []
        for event in _events(path, errors) or []:
            kind = event.get("type")
            data = event.get("data") or {}
            if kind == "session":
                session_id = str(data.get("id") or session_id)
                continue
            if kind == "user/message":
                source = data.get("source") or {}
                if source.get("kind") not in ("user", None):
                    skipped += 1
                    continue
                text = clean_text(content_text(data.get("content") or []))
                if not text or is_injected(text):
                    skipped += 1
                    continue
                messages.append(Message("user", text, _iso(event.get("time"))))
            elif kind == "assistant/message":
                message = data.get("message") or {}
                text = clean_text(content_text(message.get("content") or []))
                if not text:
                    skipped += 1
                    continue
                messages.append(Message("assistant", text, _iso(event.get("time"))))
        if messages:
            sessions.append(Session(
                source="dsh", session_id=session_id,
                title=messages[0].text[:60].replace("\n", " "),
                at=messages[0].at, path=str(path), messages=messages))
    return {"files": len(files), "sessions": sessions,
            "skipped": skipped, "errors": errors[0]}


SOURCE = Source("dsh", "DeepSeek Harness", "G", collect)
