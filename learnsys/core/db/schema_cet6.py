"""六级专项听写：只记“练了什么、错在哪”。

卡片的唯一来源仍是 `wrong_items`，复习仍是 `review_state`；
这里不复制句子正文，也不另建一套复习状态。
"""
from __future__ import annotations

CET6_DRILL_SCHEMA = """
CREATE TABLE IF NOT EXISTS cet6_drill_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    paper_id     TEXT NOT NULL,
    paper_title  TEXT NOT NULL DEFAULT '',
    section      TEXT NOT NULL DEFAULT '',
    item         TEXT NOT NULL DEFAULT '',
    sentence     INTEGER NOT NULL DEFAULT 0,
    kind         TEXT NOT NULL DEFAULT 'dictation',
    expected     TEXT NOT NULL DEFAULT '',
    answer       TEXT NOT NULL DEFAULT '',
    score        REAL NOT NULL DEFAULT 0,
    missed_json  TEXT NOT NULL DEFAULT '[]',
    extra_json   TEXT NOT NULL DEFAULT '[]',
    duration_s   INTEGER NOT NULL DEFAULT 0,
    cards_added  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cet6_drill_ts
    ON cet6_drill_attempts (ts);
CREATE INDEX IF NOT EXISTS idx_cet6_drill_sentence
    ON cet6_drill_attempts (paper_id, section, item, sentence, ts);
"""
