"""结果资产 `service_results`：一次模型调用的可复用产物。

唯一键 `(kind, target_type, target_id, scope, context_hash, prompt_version)`：
同样的输入再来一次直接命中，不再花 token。状态机：
pending → running → done / error / canceled；重新分析时旧行改 superseded。
"""
from __future__ import annotations

import json
import sqlite3

from learnsys import store

STATUSES = ("pending", "running", "done", "error", "canceled", "superseded")

COLUMNS = (
    "id", "kind", "target_type", "target_id", "scope", "context_hash",
    "prompt_version", "model", "status", "input_json", "content_json",
    "error", "tokens_in", "tokens_out", "cache_hit", "ms",
    "created_at", "updated_at",
)
_SELECT = ", ".join(COLUMNS)
_KEY = ("kind", "target_type", "target_id", "scope", "context_hash",
        "prompt_version")


def _row_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(zip(COLUMNS, row))


def create(conn: sqlite3.Connection, *, kind: str, target_type: str,
           target_id: str, scope: str, context_hash: str,
           prompt_version: str, model: str, input_json: str) -> tuple[int, bool]:
    """建一行 pending；唯一键已存在时返回既有 id（`created=False`）。"""
    stamp = store.now()
    cur = conn.execute(
        "INSERT OR IGNORE INTO service_results "
        "(kind, target_type, target_id, scope, context_hash, prompt_version, "
        " model, status, input_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
        (kind, target_type, target_id, scope, context_hash, prompt_version,
         model, input_json, stamp, stamp))
    conn.commit()
    if cur.rowcount:
        return int(cur.lastrowid or 0), True
    row = conn.execute(
        f"SELECT id FROM service_results WHERE kind=? AND target_type=? "
        "AND target_id=? AND scope=? AND context_hash=? AND prompt_version=?",
        (kind, target_type, target_id, scope, context_hash, prompt_version)).fetchone()
    return (int(row[0]), False) if row else (0, False)


def get(conn: sqlite3.Connection, result_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM service_results WHERE id = ?", (result_id,)).fetchone()
    return _row_dict(row)


def latest(conn: sqlite3.Connection, *, kind: str, target_type: str,
           target_id: str, scope: str = "") -> dict | None:
    where = "kind=? AND target_type=? AND target_id=?"
    args: list = [kind, target_type, target_id]
    if scope:
        where += " AND scope=?"
        args.append(scope)
    row = conn.execute(
        f"SELECT {_SELECT} FROM service_results WHERE {where} "
        "ORDER BY updated_at DESC, id DESC LIMIT 1", args).fetchone()
    return _row_dict(row)


def find_by_key(conn: sqlite3.Connection, *, kind: str, target_type: str,
                target_id: str, scope: str, context_hash: str,
                prompt_version: str) -> dict | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM service_results WHERE kind=? AND target_type=? "
        "AND target_id=? AND scope=? AND context_hash=? AND prompt_version=?",
        (kind, target_type, target_id, scope, context_hash,
         prompt_version)).fetchone()
    return _row_dict(row)


def find_done(conn: sqlite3.Connection, **key) -> dict | None:
    row = find_by_key(conn, **key)
    return row if row and row.get("status") == "done" else None


def claim(conn: sqlite3.Connection, result_id: int) -> bool:
    """原子地把 pending 抢成 running；已被取消/被别人抢走就返回 False。"""
    cur = conn.execute(
        "UPDATE service_results SET status='running', updated_at=? "
        "WHERE id=? AND status='pending'", (store.now(), result_id))
    conn.commit()
    return bool(cur.rowcount)


def update(conn: sqlite3.Connection, result_id: int, **fields) -> None:
    allowed = {key: value for key, value in fields.items() if key in COLUMNS}
    allowed.pop("id", None)
    allowed["updated_at"] = store.now()
    assignments = ", ".join(f"{key}=?" for key in allowed)
    conn.execute(f"UPDATE service_results SET {assignments} WHERE id=?",
                 [*allowed.values(), result_id])
    conn.commit()


def mark_superseded(conn: sqlite3.Connection, *, kind: str, target_type: str,
                    target_id: str, scope: str, context_hash: str,
                    prompt_version: str) -> int:
    cur = conn.execute(
        "UPDATE service_results SET status='superseded', updated_at=? "
        "WHERE kind=? AND target_type=? AND target_id=? AND scope=? "
        "AND context_hash=? AND prompt_version=? AND status <> 'superseded'",
        (store.now(), kind, target_type, target_id, scope, context_hash,
         prompt_version))
    conn.commit()
    return int(cur.rowcount or 0)


def recover_orphans(conn: sqlite3.Connection, *, kind: str = "") -> int:
    """进程重启后，把卡在 pending/running 的行标成可重试的错误。

    `kind` 非空时只收这一种任务 —— 录像分析先起时别把六级分析一起标错。
    """
    where = "status IN ('pending', 'running')"
    args: list = ["后台重启，任务中断，请重试", store.now()]
    if kind:
        where += " AND kind = ?"
        args.append(str(kind))
    cur = conn.execute(
        f"UPDATE service_results SET status='error', error=?, updated_at=? "
        f"WHERE {where}", args)
    conn.commit()
    return int(cur.rowcount or 0)


def list_results(conn: sqlite3.Connection, *, kind: str = "",
                 target_type: str = "", target_id: str = "", scope: str = "",
                 limit: int = 50) -> dict:
    """按条件列结果资产（不含 superseded）；返回 `{items, count}`。"""
    where = ["status <> 'superseded'"]
    args: list = []
    for column, value in (("kind", kind), ("target_type", target_type),
                          ("target_id", target_id), ("scope", scope)):
        if value:
            where.append(f"{column} = ?")
            args.append(value)
    clause = " AND ".join(where)
    limit = max(1, min(int(limit or 50), 200))
    total = conn.execute(
        f"SELECT count(*) FROM service_results WHERE {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT {_SELECT} FROM service_results WHERE {clause} "
        "ORDER BY updated_at DESC, id DESC LIMIT ?", [*args, limit]).fetchall()
    return {"items": [to_public(_row_dict(row)) for row in rows],
            "count": int(total)}


def to_public(row: dict | None) -> dict | None:
    """给前端的结果：不暴露 input_json，content_json 解析成 content。"""
    if row is None:
        return None
    out = {key: value for key, value in row.items() if key != "input_json"}
    raw = out.pop("content_json", "") or ""
    try:
        out["content"] = json.loads(raw) if raw else None
    except (json.JSONDecodeError, TypeError):
        out["content"] = None
    out["cache_hit"] = int(out.get("cache_hit") or 0)
    return out
