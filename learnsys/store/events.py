"""学习事件域：时间线 / 复盘素材 / 插件统计共用的一张事件表。"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now


def add_event(conn: sqlite3.Connection, module: str, kind: str = "note",
              title: str = "", meta: dict | None = None, ref_id: int = 0) -> int:
    """写一条学习事件（时间线 / 复盘素材 / 插件统计共用）。"""
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO events (ts, module, kind, ref_id, title, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now(), str(module or "note"), str(kind or "note"), int(ref_id or 0),
             str(title or ""), json.dumps(meta or {}, ensure_ascii=False)))
        conn.commit()
        return int(cur.lastrowid or 0)


def event_kind_counts(conn: sqlite3.Connection, module: str, *,
                      day: str = "") -> dict[str, int]:
    """某个模块按 kind 的事件数；`day` 为空 = 全量。"""
    sql = "SELECT kind, COUNT(*) FROM events WHERE module = ?"
    args: list = [str(module)]
    if day:
        sql += " AND ts LIKE ?"
        args.append(f"{str(day)[:10]}%")
    sql += " GROUP BY kind"
    return {str(kind or "note"): int(count or 0)
            for kind, count in conn.execute(sql, args).fetchall()}


def event_days(conn: sqlite3.Connection, module: str) -> set[str]:
    """某个模块有事件的日期集合（连续天数口径）。"""
    rows = conn.execute(
        "SELECT DISTINCT substr(ts, 1, 10) FROM events WHERE module = ?",
        (str(module),)).fetchall()
    return {str(row[0])[:10] for row in rows if row[0]}
