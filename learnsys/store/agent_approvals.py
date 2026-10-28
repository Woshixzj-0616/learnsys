"""P26.2 写操作提议箱：agent 每提一次写文件/跑命令，就落一行等确认。

状态只走四个值：pending → allowed / denied / expired。允许与拒绝都由
`decide_approval` 改，且只改 pending 行 —— 重复点击不会覆盖已定的结果。
"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now

STATUSES = ("pending", "allowed", "denied", "expired")
APPROVAL_KINDS = ("write", "edit", "command", "other")

_COLUMNS = (
    "id, task_id, seq, tool, kind, target, summary, preview, "
    "payload_json, status, created_at, decided_at, reason"
)


def _approval_dict(row) -> dict:
    return {
        "id": int(row[0]), "task_id": int(row[1]), "seq": int(row[2] or 0),
        "tool": row[3] or "", "kind": row[4] or "other",
        "target": row[5] or "", "summary": row[6] or "",
        "preview": row[7] or "", "payload_json": row[8] or "{}",
        "status": row[9] or "pending", "created_at": row[10] or "",
        "decided_at": row[11] or "", "reason": row[12] or "",
    }


def add_approval(conn: sqlite3.Connection, *, task_id: int, tool: str,
                 kind: str = "other", target: str = "", summary: str = "",
                 preview: str = "", payload_json: str = "{}",
                 seq: int = 0) -> int:
    kind = kind if kind in APPROVAL_KINDS else "other"
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO agent_approvals (task_id, seq, tool, kind, target, "
            "summary, preview, payload_json, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (int(task_id), int(seq or 0), str(tool), kind, str(target)[:1000],
             str(summary)[:2000], str(preview)[:8000], str(payload_json)[:20000],
             now()))
        conn.commit()
        return int(cur.lastrowid)


def get_approval(conn: sqlite3.Connection, approval_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM agent_approvals WHERE id = ?",
            (int(approval_id),)).fetchone()
    return _approval_dict(row) if row else None


def list_approvals(conn: sqlite3.Connection, task_id: int, after: int = 0,
                   limit: int = 200) -> list[dict]:
    limit = max(1, min(int(limit or 200), 500))
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM agent_approvals "
            "WHERE task_id = ? AND id > ? ORDER BY id LIMIT ?",
            (int(task_id), int(after or 0), limit)).fetchall()
    return [_approval_dict(row) for row in rows]


def pending_approvals(conn: sqlite3.Connection, task_id: int) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM agent_approvals "
            "WHERE task_id = ? AND status = 'pending' ORDER BY id",
            (int(task_id),)).fetchall()
    return [_approval_dict(row) for row in rows]


def decide_approval(conn: sqlite3.Connection, approval_id: int,
                    status: str, reason: str = "") -> bool:
    """只允许把 pending 改成终态；返回是否真的改到了。"""
    if status not in ("allowed", "denied", "expired"):
        raise ValueError(f"不认识的审批状态：{status}")
    with _LOCK:
        cur = conn.execute(
            "UPDATE agent_approvals SET status = ?, decided_at = ?, reason = ? "
            "WHERE id = ? AND status = 'pending'",
            (status, now(), str(reason or "")[:500], int(approval_id)))
        conn.commit()
        return cur.rowcount > 0


def approvals_summary(conn: sqlite3.Connection, task_id: int) -> list[dict]:
    """结果文件用：只留审计需要的字段，不带完整 payload。"""
    items = list_approvals(conn, task_id, limit=500)
    return [{key: item[key] for key in
             ("id", "tool", "kind", "target", "summary", "status",
              "created_at", "decided_at", "reason")}
            for item in items]


def payload_of(approval: dict) -> dict:
    try:
        value = json.loads(approval.get("payload_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}
