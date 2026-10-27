"""P26.1 本机 Agent 任务与事件：派活、流式日志、结果留痕。"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now


STATUSES = ("queued", "running", "done", "failed", "cancelled")
EVENT_KINDS = ("status", "text", "tool", "error", "result")

_TASK_COLUMNS = (
    "id, agent, prompt, workspace, mode, status, exit_code, created_at, "
    "started_at, ended_at, duration_ms, output_path, error, cost_usd, usage_json"
)

_UPDATE_FIELDS = {
    "status", "exit_code", "started_at", "ended_at", "duration_ms",
    "output_path", "error", "cost_usd", "usage_json",
}


def _task_dict(row) -> dict:
    usage = {}
    try:
        usage = json.loads(row[14] or "{}")
    except (json.JSONDecodeError, TypeError):
        usage = {}
    return {
        "id": int(row[0]), "agent": row[1] or "", "prompt": row[2] or "",
        "workspace": row[3] or "", "mode": row[4] or "read",
        "status": row[5] or "queued",
        "exit_code": None if row[6] is None else int(row[6]),
        "created_at": row[7] or "", "started_at": row[8] or "",
        "ended_at": row[9] or "", "duration_ms": int(row[10] or 0),
        "output_path": row[11] or "", "error": row[12] or "",
        "cost_usd": float(row[13] or 0), "usage": usage,
    }


def add_task(conn: sqlite3.Connection, *, agent: str, prompt: str,
             workspace: str = "", mode: str = "read") -> int:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO agent_tasks (agent, prompt, workspace, mode, status, "
            "created_at) VALUES (?, ?, ?, ?, 'queued', ?)",
            (str(agent), str(prompt), str(workspace), str(mode), now()))
        conn.commit()
        return int(cur.lastrowid)


def update_task(conn: sqlite3.Connection, task_id: int, **fields) -> None:
    values = {key: value for key, value in fields.items()
              if key in _UPDATE_FIELDS}
    if not values:
        return
    assignments = ", ".join(f"{key} = ?" for key in values)
    with _LOCK:
        conn.execute(f"UPDATE agent_tasks SET {assignments} WHERE id = ?",
                     [*values.values(), int(task_id)])
        conn.commit()


def get_task(conn: sqlite3.Connection, task_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_TASK_COLUMNS} FROM agent_tasks WHERE id = ?",
            (int(task_id),)).fetchone()
    return _task_dict(row) if row else None


def list_tasks(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit or 20), 200))
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_TASK_COLUMNS} FROM agent_tasks "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_task_dict(row) for row in rows]


def running_tasks(conn: sqlite3.Connection) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_TASK_COLUMNS} FROM agent_tasks "
            "WHERE status IN ('queued', 'running') ORDER BY id").fetchall()
    return [_task_dict(row) for row in rows]


def running_count(conn: sqlite3.Connection, agent: str = "") -> int:
    with _LOCK:
        if agent:
            row = conn.execute(
                "SELECT count(*) FROM agent_tasks WHERE status IN "
                "('queued', 'running') AND agent = ?", (str(agent),)).fetchone()
        else:
            row = conn.execute(
                "SELECT count(*) FROM agent_tasks WHERE status IN "
                "('queued', 'running')").fetchone()
    return int(row[0] or 0)


def add_event(conn: sqlite3.Connection, task_id: int, seq: int,
              kind: str, text: str = "") -> int:
    kind = kind if kind in EVENT_KINDS else "text"
    body = str(text or "")[:4000]
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO agent_task_events (task_id, seq, ts, kind, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(task_id), int(seq), now(), kind, body))
        conn.commit()
        return int(cur.lastrowid)


def list_events(conn: sqlite3.Connection, task_id: int,
                after: int = 0, limit: int = 1000) -> list[dict]:
    limit = max(1, min(int(limit or 1000), 5000))
    with _LOCK:
        rows = conn.execute(
            "SELECT seq, ts, kind, text FROM agent_task_events "
            "WHERE task_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (int(task_id), int(after or 0), limit)).fetchall()
    return [{"seq": int(row[0]), "ts": row[1], "kind": row[2],
             "text": row[3] or ""} for row in rows]
