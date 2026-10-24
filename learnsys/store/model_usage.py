"""模型调用账本：每一次成功调用一行。

每日成本/调用上限、成本面板都只读这张表。**不要**在别处再算一份成本。
"""
from __future__ import annotations

import sqlite3

from ._base import _LOCK, now


def add_usage(conn: sqlite3.Connection, *, source: str = "", model: str = "",
              counts: dict | None = None, cost: float = 0.0,
              currency: str = "", ts: str | None = None) -> int:
    """记一次模型调用；`counts` 用 `agent.cost.normalize_usage` 的口径。"""
    counts = counts if isinstance(counts, dict) else {}
    stamp = str(ts or now())

    def value(key: str) -> int:
        try:
            return int(counts.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    with _LOCK:
        cur = conn.execute(
            "INSERT INTO model_usage "
            "(ts, day, source, model, prompt_tokens, uncached_tokens, "
            "cache_read_tokens, cache_write_tokens, completion_tokens, "
            "total_tokens, cost, currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (stamp, stamp[:10], str(source or ""), str(model or ""),
             value("prompt_tokens"), value("uncached_tokens"),
             value("cache_read_tokens"), value("cache_write_tokens"),
             value("completion_tokens"), value("total_tokens"),
             float(cost or 0), str(currency or "")))
        conn.commit()
        return int(cur.lastrowid or 0)


def day_totals(conn: sqlite3.Connection, day: str = "") -> dict:
    """某天的总额；`day` 留空 = 今天。返回 calls / cost / tokens / currency。"""
    target = str(day or now()[:10])
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(cost), 0), COALESCE(SUM(total_tokens), 0), "
        "COALESCE(MAX(currency), '') FROM model_usage WHERE day = ?",
        (target,)).fetchone() or (0, 0, 0, "")
    return {"day": target, "calls": int(row[0] or 0),
            "cost": round(float(row[1] or 0), 6),
            "tokens": int(row[2] or 0),
            "currency": str(row[3] or "")}


def day_by_model(conn: sqlite3.Connection, day: str = "") -> list[dict]:
    """某天按模型汇总；成本面板用。"""
    target = str(day or now()[:10])
    rows = conn.execute(
        "SELECT model, COUNT(*), COALESCE(SUM(total_tokens), 0), "
        "COALESCE(SUM(cost), 0), COALESCE(MAX(currency), '') "
        "FROM model_usage WHERE day = ? GROUP BY model ORDER BY 2 DESC",
        (target,)).fetchall()
    return [{"model": str(row[0] or ""), "calls": int(row[1] or 0),
             "tokens": int(row[2] or 0), "cost": round(float(row[3] or 0), 6),
             "currency": str(row[4] or "")} for row in rows]


def recent(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, source, model, total_tokens, cost, currency "
        "FROM model_usage ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
    return [{"ts": row[0], "source": row[1], "model": row[2],
             "tokens": int(row[3] or 0), "cost": float(row[4] or 0),
             "currency": row[5] or ""} for row in rows]
