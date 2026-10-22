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
