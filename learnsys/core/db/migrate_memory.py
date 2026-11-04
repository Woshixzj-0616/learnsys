"""记忆表单表化迁移：补列、回填去重键、废弃 profile_facts 表。

只做加法 / 合并，不删用户内容。`profile_facts` 当前是 0 行，但仍按
「有数据也能安全搬」实现：先搬进 agent_memories，成功后再删旧表。
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from learnsys.core.textkey import content_key

_MEMORY_COLUMNS = (
    ("content_key", "TEXT NOT NULL DEFAULT ''"),
    ("scope", "TEXT NOT NULL DEFAULT 'global'"),
    ("evidence", "TEXT NOT NULL DEFAULT ''"),
    ("confidence", "REAL NOT NULL DEFAULT 0.5"),
    ("source", "TEXT NOT NULL DEFAULT 'user'"),
    ("source_ref", "TEXT NOT NULL DEFAULT ''"),
    ("pinned", "INTEGER NOT NULL DEFAULT 0"),
    ("use_count", "INTEGER NOT NULL DEFAULT 0"),
    ("last_used_at", "TEXT NOT NULL DEFAULT ''"),
    ("batch_id", "INTEGER NOT NULL DEFAULT 0"),
    ("archived_reason", "TEXT NOT NULL DEFAULT ''"),
)


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _add_columns(conn: sqlite3.Connection) -> None:
    have = {row[1] for row in conn.execute(
        "PRAGMA table_info(agent_memories)").fetchall()}
    for column, ddl in _MEMORY_COLUMNS:
        if column not in have:
            conn.execute(f"ALTER TABLE agent_memories ADD COLUMN {column} {ddl}")


def _backfill_keys(conn: sqlite3.Connection) -> None:
    # 旧库上唯一索引可能已经由 executescript 建好；先撤掉，回填后再建，
    # 否则第二条同键 UPDATE 会撞唯一约束。
    conn.execute("DROP INDEX IF EXISTS idx_memory_key_active")
    conn.execute("DROP INDEX IF EXISTS idx_memory_content")
    rows = conn.execute(
        "SELECT id, content FROM agent_memories").fetchall()
    for memory_id, content in rows:
        conn.execute(
            "UPDATE agent_memories SET content_key = ? WHERE id = ?",
            (content_key(content), int(memory_id)))


def _dedupe_active(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, content_key, confidence, updated_at FROM agent_memories "
        "WHERE status = 'active' ORDER BY content_key").fetchall()
    keep: dict[str, tuple] = {}
    for memory_id, key, confidence, updated_at in rows:
        key = str(key or "")
        if not key:
            continue
        score = (float(confidence or 0), str(updated_at or ""), -int(memory_id))
        current = keep.get(key)
        if current is None or score > current[0]:
            keep[key] = (score, int(memory_id))
    keep_ids = {item[1] for item in keep.values()}
    for memory_id, key, _confidence, _updated in rows:
        if key and int(memory_id) not in keep_ids:
            conn.execute(
                "UPDATE agent_memories SET status = 'archived', "
                "archived_reason = 'duplicate_content_key', updated_at = ? "
                "WHERE id = ?", (_stamp(), int(memory_id)))


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_key_active "
        "ON agent_memories (content_key) "
        "WHERE status = 'active' AND content_key <> ''")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_status "
        "ON agent_memories (status, updated_at DESC)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_scope "
        "ON agent_memories (scope, status, confidence DESC)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_candidate "
        "ON agent_memories (status, created_at DESC)")


def _retire_profile_facts(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'profile_facts'").fetchone()
    if row and str(row[0]) == "table":
        facts = conn.execute(
            "SELECT id, kind, content, evidence, confidence, status, "
            "created_at, updated_at FROM profile_facts").fetchall()
        existing = {
            str(key): int(memory_id)
            for memory_id, key in conn.execute(
                "SELECT id, content_key FROM agent_memories "
                "WHERE status = 'active'").fetchall()
        }
        for fact_id, kind, content, evidence, confidence, status, created_at, updated_at in facts:
            text = " ".join(str(content or "").split())
            if not text:
                continue
            key = content_key(text)
            if key in existing:
                conn.execute(
                    "UPDATE agent_memories SET evidence = CASE "
                    "WHEN evidence = '' THEN ? WHEN instr(evidence, ?) > 0 "
                    "THEN evidence ELSE evidence || ';' || ? END, "
                    "confidence = MAX(confidence, ?), updated_at = ? "
                    "WHERE id = ?",
                    (str(evidence or ""), str(evidence or ""), str(evidence or ""),
                     float(confidence or 0.5), str(updated_at or _stamp()),
                     existing[key]))
                continue
            cur = conn.execute(
                "INSERT INTO agent_memories (content, kind, status, created_at, "
                "updated_at, content_key, scope, evidence, confidence, source, "
                "source_ref) VALUES (?, ?, ?, ?, ?, ?, 'global', ?, ?, "
                "'profile_facts', ?)",
                (text, str(kind or "preference"),
                 "active" if str(status or "active") == "active" else "archived",
                 str(created_at or _stamp()), str(updated_at or _stamp()), key,
                 str(evidence or ""), float(confidence or 0.5),
                 f"profile_facts:{int(fact_id)}"))
            existing[key] = int(cur.lastrowid or 0)
        conn.execute("DROP TABLE profile_facts")
    conn.execute(
        "CREATE VIEW IF NOT EXISTS profile_facts AS "
        "SELECT id, kind, content, evidence, confidence, status, "
        "created_at, updated_at FROM agent_memories "
        "WHERE kind IN ('preference', 'goal', 'constraint', 'identity', 'rule')")


def migrate_memory(conn: sqlite3.Connection) -> None:
    _add_columns(conn)
    _backfill_keys(conn)
    _dedupe_active(conn)
    _create_indexes(conn)
    _retire_profile_facts(conn)
    conn.commit()
