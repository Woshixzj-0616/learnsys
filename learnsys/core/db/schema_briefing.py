"""每日简报表：一天一份，条目按 rank 展示。拼进 `schema.SCHEMA`。"""
from __future__ import annotations

BRIEFING_SCHEMA = """
CREATE TABLE IF NOT EXISTS briefings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    day               TEXT NOT NULL UNIQUE,
    status            TEXT NOT NULL DEFAULT 'pending',
    title             TEXT NOT NULL DEFAULT '今日简报',
    intro             TEXT NOT NULL DEFAULT '',
    item_count        INTEGER NOT NULL DEFAULT 0,
    model             TEXT NOT NULL DEFAULT '',
    source_stats_json TEXT NOT NULL DEFAULT '{}',
    error             TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL DEFAULT '',
    updated_at        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_briefings_status
    ON briefings (status, updated_at);
CREATE TABLE IF NOT EXISTS briefing_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_id  INTEGER NOT NULL,
    category     TEXT NOT NULL DEFAULT 'other',
    title        TEXT NOT NULL DEFAULT '',
    title_zh     TEXT NOT NULL DEFAULT '',
    summary      TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    url_key      TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    rank         INTEGER NOT NULL DEFAULT 0,
    read_at      TEXT NOT NULL DEFAULT '',
    starred      INTEGER NOT NULL DEFAULT 0,
    meta_json    TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT '',
    UNIQUE (briefing_id, url_key)
);
CREATE INDEX IF NOT EXISTS idx_briefing_items_board
    ON briefing_items (briefing_id, rank);
CREATE INDEX IF NOT EXISTS idx_briefing_items_url
    ON briefing_items (url_key);
"""
