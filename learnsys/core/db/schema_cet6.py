"""六级练习：专项听写 + 真题自评。

听写卡片的唯一来源仍是 `wrong_items`，复习仍是 `review_state`；
真题自评只记分段与对错题号，题干/音频留在试卷 `data.js`，这里都不复制。
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

CREATE TABLE IF NOT EXISTS cet6_exam_attempts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    paper_id       TEXT NOT NULL,
    paper_title    TEXT NOT NULL DEFAULT '',
    section        TEXT NOT NULL DEFAULT '',
    item           TEXT NOT NULL DEFAULT '',
    question_count INTEGER NOT NULL DEFAULT 0,
    correct_count  INTEGER NOT NULL DEFAULT 0,
    wrong_json     TEXT NOT NULL DEFAULT '[]',
    duration_s     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cet6_exam_ts
    ON cet6_exam_attempts (ts);
CREATE INDEX IF NOT EXISTS idx_cet6_exam_item
    ON cet6_exam_attempts (paper_id, section, item, ts);

CREATE TABLE IF NOT EXISTS cet6_chunk_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    paper_id     TEXT NOT NULL,
    paper_title  TEXT NOT NULL DEFAULT '',
    section      TEXT NOT NULL DEFAULT '',
    item         TEXT NOT NULL DEFAULT '',
    sentence     INTEGER NOT NULL DEFAULT 0,
    expected     TEXT NOT NULL DEFAULT '',
    answer       TEXT NOT NULL DEFAULT '',
    score        REAL NOT NULL DEFAULT 0,
    missed_json  TEXT NOT NULL DEFAULT '[]',
    extra_json   TEXT NOT NULL DEFAULT '[]',
    duration_s   INTEGER NOT NULL DEFAULT 0,
    cards_added  INTEGER NOT NULL DEFAULT 0,
    chunk_count  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cet6_chunk_ts
    ON cet6_chunk_attempts (ts);
CREATE INDEX IF NOT EXISTS idx_cet6_chunk_sentence
    ON cet6_chunk_attempts (paper_id, section, item, sentence, ts);
"""
