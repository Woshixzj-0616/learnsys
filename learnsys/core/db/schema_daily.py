"""每日积累：纠音池 + 当天三条线的条目。

- `cet6_pron_items` 是「你笔记里没听出/听错」的长期池，跨天累积；
- `cet6_accum_items` 是每天冻结的一份清单，状态只影响进度。
题干、原句、词级时间轴仍在试卷文件，这里只存展示所需的短字段。
"""
from __future__ import annotations

DAILY_SCHEMA = """
CREATE TABLE IF NOT EXISTS cet6_pron_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id    TEXT NOT NULL,
    paper_title TEXT NOT NULL DEFAULT '',
    section     TEXT NOT NULL DEFAULT '',
    item        TEXT NOT NULL DEFAULT '',
    sentence    INTEGER NOT NULL DEFAULT 0,
    target      TEXT NOT NULL,
    heard_as    TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'unknown',
    note        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'new',
    attempts    INTEGER NOT NULL DEFAULT 0,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    last_used   TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cet6_pron_point
    ON cet6_pron_items (paper_id, section, item, sentence, target);
CREATE INDEX IF NOT EXISTS idx_cet6_pron_status
    ON cet6_pron_items (status, last_seen);

CREATE TABLE IF NOT EXISTS cet6_accum_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    day          TEXT NOT NULL,
    kind         TEXT NOT NULL,
    ref_key      TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'new',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cet6_accum_day
    ON cet6_accum_items (day, kind, ref_key);
CREATE INDEX IF NOT EXISTS idx_cet6_accum_day_kind
    ON cet6_accum_items (day, kind);
"""
