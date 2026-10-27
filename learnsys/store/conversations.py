"""v2 会话 / 消息域（Web 工作台用）。"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now


# ---- v2 会话 / 消息（Web 工作台用）----

def create_conversation(conn: sqlite3.Connection, title: str = "",
                        module: str = "ask", mode: str = "explain",
                        origin: str = "ask", recording_id: int = 0) -> int:
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO conversations (title, module, mode, started_at, updated_at, "
            "origin, recording_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title or "新对话", module, mode, stamp, stamp,
             str(origin or "ask"), int(recording_id or 0)))
        conn.commit()
        return int(cur.lastrowid or 0)


def touch_conversation(conn: sqlite3.Connection, conversation_id: int,
                       title: str = "") -> None:
    with _LOCK:
        if title:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now(), conversation_id))
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now(), conversation_id))
        conn.commit()


def add_message(conn: sqlite3.Connection, conversation_id: int, role: str,
                content, ts: str = "", result_id: int = 0) -> int:
    """content 可以是字符串或 dict/list；统一存 JSON。

    `result_id` 只记引用（service_results 的 id），正文仍在那张表里。
    """
    payload = content if isinstance(content, str) else json.dumps(
        content, ensure_ascii=False)
    stamp = ts or now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content_json, ts, result_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, payload, stamp, int(result_id or 0)))
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (stamp, conversation_id))
        conn.commit()
        return int(cur.lastrowid or 0)


def set_conversation_summary(conn: sqlite3.Connection, conversation_id: int,
                             summary: str) -> None:
    """写会话摘要（更早对话的压缩）；空串等于清空。"""
    with _LOCK:
        conn.execute(
            "UPDATE conversations SET summary = ?, updated_at = ? WHERE id = ?",
            (" ".join(str(summary or "").split())[:400], now(), int(conversation_id)))
        conn.commit()


def get_conversation(conn: sqlite3.Connection, conversation_id: int):
    with _LOCK:
        return conn.execute(
            "SELECT id, title, module, mode, summary, started_at, updated_at, "
            "origin, recording_id FROM conversations WHERE id = ?",
            (conversation_id,)).fetchone()


def list_conversations(conn: sqlite3.Connection, limit: int = 20,
                       module: str = "ask", origin: str = "",
                       recording_id: int = 0) -> list[dict]:
    """会话列表；`module` 默认只看问一问，插件内部会话（复盘/测验）不混进来。

    `origin=video` + `recording_id` 用来只看某段录像里的对话；列表仍属于问一问
    （module=ask），只是带来源标记。
    """
    where, args = [], []
    if module:
        where.append("c.module = ?")
        args.append(module)
    if origin:
        where.append("c.origin = ?")
        args.append(str(origin))
    if recording_id:
        where.append("c.recording_id = ?")
        args.append(int(recording_id))
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    args.append(limit)
    with _LOCK:
        rows = conn.execute(
            "SELECT c.id, c.title, c.module, c.mode, c.started_at, c.updated_at, "
            "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id), "
            "c.origin, c.recording_id, COALESCE(s.title, '') "
            "FROM conversations c LEFT JOIN sessions s ON s.id = c.recording_id "
            f"{clause} ORDER BY c.updated_at DESC, c.id DESC LIMIT ?",
            args).fetchall()
    return [
        {"id": row[0], "title": row[1] or "", "module": row[2] or "ask",
         "mode": row[3] or "explain", "started_at": row[4] or "",
         "updated_at": row[5] or "", "messages": int(row[6] or 0),
         "origin": row[7] or "ask", "recording_id": int(row[8] or 0),
         "recording_title": row[9] or ""}
        for row in rows
    ]


def conversation_messages(conn: sqlite3.Connection, conversation_id: int) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            "SELECT id, role, content_json, ts, result_id FROM messages "
            "WHERE conversation_id = ? ORDER BY id", (conversation_id,)).fetchall()
    out = []
    for row in rows:
        try:
            content = json.loads(row[2])
        except (json.JSONDecodeError, TypeError):
            content = row[2]
        out.append({"id": row[0], "role": row[1], "content": content, "ts": row[3],
                    "result_id": int(row[4] or 0)})
    return out
