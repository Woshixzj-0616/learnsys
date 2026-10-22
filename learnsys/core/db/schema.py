"""统一库建表语句：一份 SCHEMA 就是唯一真相。

迁移只做加法：CREATE IF NOT EXISTS / ADD COLUMN / CREATE INDEX IF NOT EXISTS。
"""
from __future__ import annotations


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT
);
CREATE TABLE IF NOT EXISTS window_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts         TEXT NOT NULL,
    process    TEXT,
    title      TEXT
);
CREATE INDEX IF NOT EXISTS idx_window_events_session ON window_events (session_id, ts);
CREATE TABLE IF NOT EXISTS transcripts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts_start   TEXT NOT NULL,
    ts_end     TEXT NOT NULL,
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transcripts_session ON transcripts (session_id, ts_start);
CREATE INDEX IF NOT EXISTS idx_transcripts_ts ON transcripts (ts_start);
CREATE TABLE IF NOT EXISTS asks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    question       TEXT NOT NULL,
    answer         TEXT NOT NULL,
    ms             INTEGER,
    first_ms       INTEGER,
    backend        TEXT,
    kind           TEXT,
    image_path     TEXT,
    thread         TEXT,
    starred        INTEGER DEFAULT 0,
    review_stage   INTEGER DEFAULT 0,
    last_remind    TEXT,
    conversation_id INTEGER,
    provider       TEXT,
    model          TEXT
);
CREATE INDEX IF NOT EXISTS idx_asks_ts ON asks (ts);
CREATE TABLE IF NOT EXISTS frame_text (
    path TEXT PRIMARY KEY,
    ts   TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_frame_text_ts ON frame_text (ts);
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT,
    module     TEXT,
    mode       TEXT,
    summary    TEXT,
    started_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content_json    TEXT NOT NULL,
    ts              TEXT NOT NULL,
    result_id       INTEGER NOT NULL DEFAULT 0   -- 引用 service_results，不复制正文
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id, id);
CREATE TABLE IF NOT EXISTS cet6_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT,
    paper_id      TEXT,
    paper_title   TEXT,
    section       TEXT,
    item          TEXT,
    sentence      INTEGER,
    tags          TEXT,
    note          TEXT,
    loops         INTEGER,
    plays         INTEGER,
    analysis_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_cet6_ts ON cet6_events (ts);
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT,
    module    TEXT,
    kind      TEXT,
    ref_id    INTEGER,
    title     TEXT,
    meta_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
CREATE TABLE IF NOT EXISTS migrated_sources (
    path        TEXT PRIMARY KEY,
    migrated_at TEXT,
    counts_json TEXT
);
CREATE TABLE IF NOT EXISTS materials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'note',
    source      TEXT NOT NULL DEFAULT 'note',
    path        TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    chars       INTEGER NOT NULL DEFAULT 0,
    pages       INTEGER NOT NULL DEFAULT 0,
    size        INTEGER NOT NULL DEFAULT 0,
    sha256      TEXT,
    course      TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active',
    meta_json   TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    last_opened TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_materials_status ON materials (status, updated_at);
DROP INDEX IF EXISTS idx_materials_sha;
CREATE UNIQUE INDEX IF NOT EXISTS idx_materials_sha_active
    ON materials (sha256)
    WHERE sha256 IS NOT NULL AND sha256 <> '' AND status = 'active';
CREATE TABLE IF NOT EXISTS wrong_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'manual',
    source_id    TEXT,
    question     TEXT NOT NULL,
    answer       TEXT NOT NULL DEFAULT '',
    my_answer    TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',
    auto         INTEGER NOT NULL DEFAULT 0,
    review_stage INTEGER NOT NULL DEFAULT 0,
    last_review  TEXT NOT NULL DEFAULT '',
    mastered     INTEGER NOT NULL DEFAULT 0,
    material_id  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_wrong_ts ON wrong_items (ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wrong_source
    ON wrong_items (source, source_id)
    WHERE source_id IS NOT NULL AND source_id <> '';
CREATE TABLE IF NOT EXISTS service_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL,
    target_type    TEXT NOT NULL DEFAULT '',
    target_id      TEXT NOT NULL DEFAULT '',
    scope          TEXT NOT NULL DEFAULT '',
    context_hash   TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    model          TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pending',
    input_json     TEXT NOT NULL DEFAULT '',
    content_json   TEXT NOT NULL DEFAULT '',
    error          TEXT NOT NULL DEFAULT '',
    tokens_in      INTEGER NOT NULL DEFAULT 0,
    tokens_out     INTEGER NOT NULL DEFAULT 0,
    cache_hit      INTEGER NOT NULL DEFAULT 0,
    ms             INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
-- 只约束「当前版本」：force 重分析时旧行变 superseded，允许同一键再建一行
CREATE UNIQUE INDEX IF NOT EXISTS idx_service_results_key
ON service_results (kind, target_type, target_id, scope, context_hash, prompt_version)
WHERE status <> 'superseded';
CREATE INDEX IF NOT EXISTS idx_service_results_latest
ON service_results (kind, target_type, target_id, scope, updated_at DESC);
CREATE TABLE IF NOT EXISTS service_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    trace_id   TEXT NOT NULL DEFAULT '',
    result_id  INTEGER,
    surface    TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT '',
    model      TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'running',
    ms         INTEGER NOT NULL DEFAULT 0,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cache_hit  INTEGER NOT NULL DEFAULT 0,
    error      TEXT NOT NULL DEFAULT '',
    meta_json  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_service_runs_ts ON service_runs (ts);
CREATE INDEX IF NOT EXISTS idx_service_runs_result ON service_runs (result_id);
CREATE TABLE IF NOT EXISTS cet6_progress (
    paper_id    TEXT NOT NULL,
    paper_title TEXT NOT NULL DEFAULT '',
    section     TEXT NOT NULL,
    item        TEXT NOT NULL,
    sentence    INTEGER NOT NULL,
    en          TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    loops       INTEGER NOT NULL DEFAULT 0,
    plays       INTEGER NOT NULL DEFAULT 0,
    done        INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (paper_id, section, item, sentence)
);
CREATE INDEX IF NOT EXISTS idx_cet6_progress_item
ON cet6_progress (paper_id, section, item);
CREATE TABLE IF NOT EXISTS vocab_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word        TEXT NOT NULL,
    normalized  TEXT NOT NULL,
    meaning     TEXT NOT NULL DEFAULT '',
    phonetic    TEXT NOT NULL DEFAULT '',
    context     TEXT NOT NULL DEFAULT '',
    paper_id    TEXT NOT NULL DEFAULT '',
    paper_title TEXT NOT NULL DEFAULT '',
    sentence    INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'cet6',
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vocab_word ON vocab_items (normalized);
CREATE INDEX IF NOT EXISTS idx_vocab_recent
ON vocab_items (status, updated_at DESC);
CREATE TABLE IF NOT EXISTS review_state (
    item_type      TEXT NOT NULL,
    item_id        INTEGER NOT NULL,
    state          TEXT NOT NULL DEFAULT 'new',
    due            TEXT NOT NULL,
    stability      REAL NOT NULL DEFAULT 0,
    difficulty     REAL NOT NULL DEFAULT 0,
    reps           INTEGER NOT NULL DEFAULT 0,
    lapses         INTEGER NOT NULL DEFAULT 0,
    last_review    TEXT NOT NULL DEFAULT '',
    scheduled_days INTEGER NOT NULL DEFAULT 0,
    elapsed_days   INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (item_type, item_id)
);
CREATE INDEX IF NOT EXISTS idx_review_due ON review_state (due);
CREATE TABLE IF NOT EXISTS agent_memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'preference',
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_content
    ON agent_memories (content) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_memory_status
    ON agent_memories (status, updated_at DESC);
CREATE TABLE IF NOT EXISTS agent_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL UNIQUE,
    conversation_id INTEGER NOT NULL DEFAULT 0,
    question        TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    mode            TEXT NOT NULL DEFAULT '',
    started_at      TEXT NOT NULL DEFAULT '',
    finished_at     TEXT NOT NULL DEFAULT '',
    first_ms        INTEGER,
    total_ms        INTEGER NOT NULL DEFAULT 0,
    steps           INTEGER NOT NULL DEFAULT 0,
    stop_reason     TEXT NOT NULL DEFAULT '',
    usage_json      TEXT NOT NULL DEFAULT '{}',
    trace_json      TEXT NOT NULL DEFAULT '[]',
    check_ok        INTEGER,
    error           TEXT NOT NULL DEFAULT '',
    tool_count      INTEGER NOT NULL DEFAULT 0,
    model_calls     INTEGER NOT NULL DEFAULT 0,
    error_count     INTEGER NOT NULL DEFAULT 0,
    cost            REAL NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation
    ON agent_runs (conversation_id, id DESC);
CREATE TABLE IF NOT EXISTS review_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    item_type      TEXT NOT NULL,
    item_id        INTEGER NOT NULL,
    rating         INTEGER NOT NULL,
    state_before   TEXT NOT NULL DEFAULT '',
    due_before     TEXT NOT NULL DEFAULT '',
    due_after      TEXT NOT NULL DEFAULT '',
    stability      REAL NOT NULL DEFAULT 0,
    difficulty     REAL NOT NULL DEFAULT 0,
    elapsed_days   INTEGER NOT NULL DEFAULT 0,
    scheduled_days INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_review_log_item
ON review_log (item_type, item_id, id DESC);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_idx USING fts5(
    body,
    module UNINDEXED,
    ref_id UNINDEXED,
    ts UNINDEXED,
    tokenize='trigram'
);
"""
