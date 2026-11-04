"""Agent 长期记忆：跨会话偏好、规矩、身份/目标/约束。

一张表就是唯一真相：Agent 的工具写它，导入器写它，界面读它，
系统提示词每轮按作用域挑着注入它。`profile_facts` 只是它的兼容视图。
"""
from __future__ import annotations

import sqlite3

from learnsys.core.textkey import content_key

from ._base import _LOCK, now

_COLUMNS = (
    "id, content, kind, status, created_at, updated_at, content_key, scope, "
    "evidence, confidence, source, source_ref, pinned, use_count, "
    "last_used_at, batch_id, archived_reason"
)

KINDS = ("preference", "rule", "identity", "goal", "constraint", "project")
STATUSES = ("active", "candidate", "archived", "superseded")


def _row(row) -> dict:
    return {
        "id": int(row[0]), "content": row[1] or "", "kind": row[2] or "preference",
        "status": row[3] or "active", "created_at": row[4] or "",
        "updated_at": row[5] or "", "content_key": row[6] or "",
        "scope": row[7] or "global", "evidence": row[8] or "",
        "confidence": float(row[9] or 0), "source": row[10] or "user",
        "source_ref": row[11] or "", "pinned": int(row[12] or 0),
        "use_count": int(row[13] or 0), "last_used_at": row[14] or "",
        "batch_id": int(row[15] or 0), "archived_reason": row[16] or "",
    }


def _clean(text: str) -> str:
    return " ".join(str(text or "").split())


def list_memories(conn: sqlite3.Connection, *, limit: int = 50,
                  include_archived: bool = False, status: str = "",
                  kinds: tuple[str, ...] = (), scope: str = "") -> list[dict]:
    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    elif not include_archived:
        clauses.append("status = 'active'")
    if kinds:
        clauses.append("kind IN (" + ",".join("?" for _ in kinds) + ")")
        params.extend(kinds)
    if scope:
        clauses.append("scope = ?")
        params.append(scope)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM agent_memories {where} "
            "ORDER BY id", params).fetchall()
    return [_row(row) for row in rows[:max(1, int(limit))]]


def get_memory(conn: sqlite3.Connection, memory_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM agent_memories WHERE id = ?",
            (int(memory_id),)).fetchone()
    return _row(row) if row else None


def _merge(existing: str, incoming: str) -> str:
    incoming = _clean(incoming)
    if not incoming or incoming in str(existing or ""):
        return str(existing or "")
    existing = str(existing or "")
    return incoming if not existing else existing + ";" + incoming


def add_memory(conn: sqlite3.Connection, content: str, kind: str = "preference",
               *, scope: str = "global", evidence: str = "",
               confidence: float = 0.5, source: str = "user",
               source_ref: str = "", pinned: int = 0, batch_id: int = 0,
               status: str = "active") -> tuple[int, bool]:
    """记一条长期记忆；同内容只留一条（重复说 = 刷新时间，不是再记一遍）。

    返回 `(id, created)`：`created=False` 表示命中了已有记忆（只刷新/合并）。
    """
    text = _clean(content)
    if not text:
        return 0, False
    key = content_key(text)
    kind = kind if kind in KINDS else "preference"
    status = status if status in STATUSES else "active"
    stamp = now()
    with _LOCK:
        row = conn.execute(
            "SELECT id, status, evidence, confidence, source FROM agent_memories "
            "WHERE content_key = ? "
            "ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id DESC LIMIT 1",
            (key,)).fetchone()
        if row:
            old_status = str(row[1] or "active")
            try:
                conn.execute(
                    "UPDATE agent_memories SET status = ?, updated_at = ?, "
                    "evidence = ?, confidence = MAX(confidence, ?), "
                    "source = CASE WHEN source = '' OR source = 'user' THEN ? "
                    "ELSE source END WHERE id = ?",
                    (status, stamp, _merge(row[2] or "", evidence),
                     float(confidence or 0), source or "user", int(row[0])))
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
            return int(row[0]), old_status != "active"
        try:
            cur = conn.execute(
                "INSERT INTO agent_memories (content, kind, status, created_at, "
                "updated_at, content_key, scope, evidence, confidence, source, "
                "source_ref, pinned, batch_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (text, kind, status, stamp, stamp, key, scope or "global",
                 _clean(evidence), float(confidence or 0), source or "user",
                 source_ref or "", 1 if pinned else 0, int(batch_id or 0)))
            conn.commit()
            return int(cur.lastrowid or 0), True
        except sqlite3.IntegrityError:
            conn.rollback()
            active = conn.execute(
                "SELECT id FROM agent_memories WHERE content_key = ? "
                "AND status = 'active' LIMIT 1", (key,)).fetchone()
            return int(active[0]) if active else 0, False


def update_memory(conn: sqlite3.Connection, memory_id: int, content: str,
                  *, kind: str | None = None, scope: str | None = None,
                  evidence: str | None = None,
                  confidence: float | None = None,
                  status: str | None = None,
                  pinned: int | None = None) -> bool:
    text = _clean(content)
    if not text:
        return False
    sets = ["content = ?", "content_key = ?", "updated_at = ?"]
    params: list[object] = [text, content_key(text), now()]
    if kind is not None and kind in KINDS:
        sets.append("kind = ?")
        params.append(kind)
    if scope is not None:
        sets.append("scope = ?")
        params.append(scope or "global")
    if evidence is not None:
        sets.append("evidence = ?")
        params.append(_clean(evidence))
    if confidence is not None:
        sets.append("confidence = ?")
        params.append(float(confidence))
    if status is not None and status in STATUSES:
        sets.append("status = ?")
        params.append(status)
    if pinned is not None:
        sets.append("pinned = ?")
        params.append(1 if pinned else 0)
    params.append(int(memory_id))
    with _LOCK:
        try:
            cur = conn.execute(
                f"UPDATE agent_memories SET {', '.join(sets)} "
                "WHERE id = ? AND status != 'archived'", params)
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return False
        return bool(cur.rowcount)


def delete_memory(conn: sqlite3.Connection, memory_id: int,
                  reason: str = "user_forgot") -> bool:
    """软删除：留一条 status='archived' 的行，方便以后排查「它怎么忘掉的」。"""
    with _LOCK:
        cur = conn.execute(
            "UPDATE agent_memories SET status = 'archived', archived_reason = ?, "
            "updated_at = ? WHERE id = ? AND status != 'archived'",
            (reason, now(), int(memory_id)))
        conn.commit()
        return bool(cur.rowcount)


def promote_memory(conn: sqlite3.Connection, memory_id: int,
                   confidence: float = 0.75) -> bool:
    with _LOCK:
        cur = conn.execute(
            "UPDATE agent_memories SET status = 'active', "
            "confidence = MAX(confidence, ?), updated_at = ? WHERE id = ?",
            (float(confidence), now(), int(memory_id)))
        conn.commit()
        return bool(cur.rowcount)


def mark_used(conn: sqlite3.Connection, memory_ids) -> None:
    ids = [int(item) for item in memory_ids if int(item or 0) > 0]
    if not ids:
        return
    stamp = now()
    with _LOCK:
        try:
            conn.executemany(
                "UPDATE agent_memories SET use_count = use_count + 1, "
                "last_used_at = ? WHERE id = ?",
                [(stamp, memory_id) for memory_id in ids])
            conn.commit()
        except Exception:
            conn.rollback()
