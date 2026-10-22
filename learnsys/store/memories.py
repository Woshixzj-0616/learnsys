"""Agent 长期记忆：跨会话偏好与用户强调的规矩。

一张表就是唯一真相：Agent 的工具写它，界面读它，系统提示词每轮注入它。
"""
from __future__ import annotations

import sqlite3

from ._base import _LOCK, now


# ---- Agent 长期记忆（跨会话偏好 / 用户强调的规矩） ----
#
# 为什么要落库而不是塞进提示词：用户说「以后都用中文」「示例代码用 C++」这类话
# 必须**活过这一轮对话**。只写提示词 = 每次重新交代，系统层面等于没有记忆。
# 一张表就是唯一真相：Agent 的工具写它，界面读它，系统提示词每轮注入它。

def list_memories(conn: sqlite3.Connection, *, limit: int = 50,
                  include_archived: bool = False) -> list[dict]:
    where = "" if include_archived else "WHERE status = 'active'"
    with _LOCK:
        rows = conn.execute(
            f"SELECT id, content, kind, status, created_at, updated_at "
            f"FROM agent_memories {where} ORDER BY id", ()).fetchall()
    return [
        {"id": int(row[0]), "content": row[1] or "", "kind": row[2] or "preference",
         "status": row[3] or "active", "created_at": row[4] or "",
         "updated_at": row[5] or ""}
        for row in rows[:max(1, int(limit))]
    ]


def add_memory(conn: sqlite3.Connection, content: str,
               kind: str = "preference") -> tuple[int, bool]:
    """记一条长期记忆；同样内容只留一条（重复说 = 刷新时间，不是再记一遍）。"""
    text = " ".join(str(content or "").split())
    if not text:
        return 0, False
    stamp = now()
    with _LOCK:
        row = conn.execute(
            "SELECT id, status FROM agent_memories WHERE content = ? "
            "ORDER BY id DESC LIMIT 1", (text,)).fetchone()
        if row:
            try:
                conn.execute(
                    "UPDATE agent_memories SET status = 'active', updated_at = ? WHERE id = ?",
                    (stamp, row[0]))
                conn.commit()
            except sqlite3.IntegrityError:
                # 另一条同内容已经启用：没有「两条一样的记忆」这种东西
                conn.rollback()
            return int(row[0]), str(row[1]) != "active"
        try:
            cur = conn.execute(
                "INSERT INTO agent_memories (content, kind, status, created_at, updated_at) "
                "VALUES (?, ?, 'active', ?, ?)", (text, kind or "preference", stamp, stamp))
            conn.commit()
            return int(cur.lastrowid or 0), True
        except sqlite3.IntegrityError:
            conn.rollback()
            active = conn.execute(
                "SELECT id FROM agent_memories WHERE content = ? AND status = 'active' "
                "LIMIT 1", (text,)).fetchone()
            return int(active[0]) if active else 0, False


def update_memory(conn: sqlite3.Connection, memory_id: int, content: str) -> bool:
    text = " ".join(str(content or "").split())
    if not text:
        return False
    with _LOCK:
        try:
            cur = conn.execute(
                "UPDATE agent_memories SET content = ?, updated_at = ? "
                "WHERE id = ? AND status = 'active'", (text, now(), int(memory_id)))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return False
        return bool(cur.rowcount)


def delete_memory(conn: sqlite3.Connection, memory_id: int) -> bool:
    """软删除：留一条 status='archived' 的行，方便以后排查「它怎么忘掉的」。"""
    with _LOCK:
        cur = conn.execute(
            "UPDATE agent_memories SET status = 'archived', updated_at = ? "
            "WHERE id = ? AND status = 'active'", (now(), int(memory_id)))
        conn.commit()
        return bool(cur.rowcount)
