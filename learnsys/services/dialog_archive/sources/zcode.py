"""ZCode：从 sqlite 的 session/message/part 三张表还原对话。

数据库先复制到临时目录再只读打开，避免锁住正在使用的 ZCode。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
import sqlite3
import tempfile

from ..model import Message, Session, Source
from .common import before_cutoff, clean_text, content_text, is_injected

DB = pathlib.Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"


def _iso(value) -> str:
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


def _json(raw) -> dict:
    try:
        value = json.loads(raw or "")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def collect(cutoff_ts: float) -> dict:
    if not DB.exists() or not before_cutoff(DB, cutoff_ts):
        return {"files": 0, "sessions": [], "skipped": 0, "errors": 0}
    tmp = pathlib.Path(tempfile.mkdtemp())
    target = tmp / "db.sqlite"
    try:
        shutil.copy2(DB, target)
        conn = sqlite3.connect(str(target))
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        return {"files": 1, "sessions": [], "skipped": 0, "errors": 1}
    try:
        titles = {}
        try:
            titles = {str(row[0]): str(row[1] or "")
                      for row in conn.execute("SELECT id, title FROM session")}
        except sqlite3.Error:
            pass
        parts: dict[str, list[str]] = {}
        try:
            for message_id, raw in conn.execute(
                    "SELECT message_id, data FROM part ORDER BY sequence"):
                data = _json(raw)
                if data.get("type") != "text":
                    continue
                text = clean_text(str(data.get("text") or ""))
                if text:
                    parts.setdefault(str(message_id), []).append(text)
        except sqlite3.Error:
            pass
        grouped: dict[str, list[Message]] = {}
        order: list[str] = []
        for message_id, session_id, raw in conn.execute(
                "SELECT id, session_id, data FROM message "
                "ORDER BY time_created, sequence"):
            data = _json(raw)
            role = data.get("role")
            if role not in ("user", "assistant"):
                continue
            text = "\n".join(parts.get(str(message_id), []))
            if not text:
                text = clean_text(content_text(data.get("content")))
            if not text or (role == "user" and is_injected(text)):
                continue
            sid = str(session_id)
            if sid not in grouped:
                grouped[sid] = []
                order.append(sid)
            grouped[sid].append(Message(role, text, _iso(
                (data.get("time") or {}).get("created"))))
        sessions = []
        for sid in order:
            messages = grouped[sid]
            sessions.append(Session(
                source="zcode", session_id=sid,
                title=(titles.get(sid) or messages[0].text[:60]).replace("\n", " "),
                at=messages[0].at, path=str(DB), messages=messages))
        return {"files": 1, "sessions": sessions,
                "skipped": 0, "errors": 0}
    finally:
        try:
            conn.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


SOURCE = Source("zcode", "ZCode", "F", collect)
