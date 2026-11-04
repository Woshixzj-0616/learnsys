"""记忆系统扩展表：导入批次、抽取断点、画像兼容视图。

只做加法：CREATE IF NOT EXISTS。表随统一库 SCHEMA_VERSION 一起建。
"""
from __future__ import annotations

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_batches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,                 -- dialog_archive / fact_extract / profile_import
    status       TEXT NOT NULL DEFAULT 'running', -- running / sealed / done / failed / cancelled
    archive_id   TEXT NOT NULL DEFAULT '',
    archive_path TEXT NOT NULL DEFAULT '',
    cutoff_at    TEXT NOT NULL DEFAULT '',
    body_sha256  TEXT NOT NULL DEFAULT '',
    file_sha256  TEXT NOT NULL DEFAULT '',
    stats_json   TEXT NOT NULL DEFAULT '{}',
    missing_json TEXT NOT NULL DEFAULT '[]',
    error        TEXT NOT NULL DEFAULT '',
    started_at   TEXT NOT NULL,
    finished_at  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_memory_batches_kind
    ON memory_batches (kind, id DESC);

CREATE TABLE IF NOT EXISTS memory_extract_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    INTEGER NOT NULL,
    chunk_key   TEXT NOT NULL UNIQUE,
    source      TEXT NOT NULL DEFAULT '',
    session_ids TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending', -- pending / running / done / failed
    facts_json  TEXT NOT NULL DEFAULT '[]',
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_chunks_batch
    ON memory_extract_chunks (batch_id, status);

-- profile_facts 兼容视图由 migrate_memory 创建：老库 executescript 时
-- agent_memories 还没有 evidence/confidence 列，不能在这里建视图。
"""
