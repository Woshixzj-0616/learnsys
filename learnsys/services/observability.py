"""服务调用流水 `service_runs`：只做观测，永不把异常抛给业务。"""
from __future__ import annotations

import json
import sqlite3
import uuid

from learnsys import diagnostics, store


def start_run(*, surface: str = "", kind: str = "", model: str = "",
              result_id: int | None = None, meta: dict | None = None,
              conn: sqlite3.Connection | None = None) -> int:
    """记一条运行流水。传 `conn` 就复用调用方的库（同一任务别开两条连接）。"""
    own = conn is None
    try:
        conn = conn if conn is not None else store.connect()
        try:
            cur = conn.execute(
                "INSERT INTO service_runs "
                "(ts, trace_id, result_id, surface, kind, model, status, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
                (store.now(), uuid.uuid4().hex[:12], result_id, surface or "",
                 kind or "", model or "", json.dumps(meta or {}, ensure_ascii=False)))
            conn.commit()
            return int(cur.lastrowid or 0)
        finally:
            if own:
                conn.close()
    except Exception as exc:
        diagnostics.log_swallow("写 service_runs 开始流水", exc)
        return 0


def finish_run(run_id: int, *, status: str, ms: int, tokens_in: int = 0,
               tokens_out: int = 0, cache_hit: int = 0, error: str = "",
               conn: sqlite3.Connection | None = None) -> None:
    if not run_id:
        return
    own = conn is None
    try:
        conn = conn if conn is not None else store.connect()
        try:
            conn.execute(
                "UPDATE service_runs SET status=?, ms=?, tokens_in=?, tokens_out=?, "
                "cache_hit=?, error=? WHERE id=?",
                (status or "done", int(ms or 0), int(tokens_in or 0),
                 int(tokens_out or 0), 1 if cache_hit else 0,
                 str(error or "")[:1000], run_id))
            conn.commit()
        finally:
            if own:
                conn.close()
    except Exception as exc:
        diagnostics.log_swallow("写 service_runs 完成流水", exc)


def recent_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts, trace_id, result_id, surface, kind, model, status, ms, "
        "tokens_in, tokens_out, cache_hit, error, meta_json "
        "FROM service_runs ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit or 50), 200)),)).fetchall()
    out = []
    for row in rows:
        try:
            meta = json.loads(row[13]) if row[13] else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        out.append({
            "id": row[0], "ts": row[1], "trace_id": row[2], "result_id": row[3],
            "surface": row[4], "kind": row[5], "model": row[6], "status": row[7],
            "ms": int(row[8] or 0), "tokens_in": int(row[9] or 0),
            "tokens_out": int(row[10] or 0), "cache_hit": bool(row[11]),
            "error": row[12] or "", "meta": meta,
        })
    return out
