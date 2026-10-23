"""连接与基础统计：打开统一库、补列、建 FTS、首次旧收藏迁移。"""
from __future__ import annotations

import datetime as dt
import pathlib
import sqlite3
import threading

from learnsys import config

from .schema import SCHEMA

_LOCK = threading.Lock()


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _seed_knowledge(conn: sqlite3.Connection) -> None:
    """种 8 个知识点类目 + 回填 cutoff；幂等。"""
    from learnsys import knowledge

    stamp = now()
    for item in knowledge.CATEGORIES:
        conn.execute(
            "INSERT OR IGNORE INTO knowledge_points (name, kind, sort, active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (item["name"], item["kind"], int(item["sort"]), stamp))
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('knowledge_attempts_since', ?)",
        (stamp,))
    conn.commit()


def connect(path=None) -> sqlite3.Connection:
    """打开统一库（缺省 = `config.db_path()`），建表 + 迁移 + FTS。"""
    # 延迟导入：migrate 也要用 connect，顶层导入会绕成环
    from .fts import _ensure_fts
    from .migrate import _import_legacy_starred, _migrate_columns

    target = pathlib.Path(path) if path else config.db_path()
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    _ensure_fts(conn)
    _import_legacy_starred(conn)
    _seed_knowledge(conn)
    return conn


def counts(conn: sqlite3.Connection) -> dict:
    def one(sql: str) -> int:
        try:
            return int(conn.execute(sql).fetchone()[0] or 0)
        except sqlite3.Error:
            return 0
    return {
        "asks": one("SELECT COUNT(*) FROM asks"),
        "transcripts": one("SELECT COUNT(*) FROM transcripts"),
        "window_events": one("SELECT COUNT(*) FROM window_events"),
        "sessions": one("SELECT COUNT(*) FROM sessions"),
        "frame_text": one("SELECT COUNT(*) FROM frame_text"),
        "cet6_events": one("SELECT COUNT(*) FROM cet6_events"),
        "messages": one("SELECT COUNT(*) FROM messages"),
        "wrong_items": one("SELECT COUNT(*) FROM wrong_items"),
        "materials": one("SELECT COUNT(*) FROM materials"),
    }
