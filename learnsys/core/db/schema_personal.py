"""个人 AI 工作台的四张基础表：偏好 / 项目引用 / 订阅 / 每日卡片。

只做加法：`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`。
拼进 `schema.SCHEMA` 末尾；生活事件仍写 `events(module='life')`，不另建平行表。
"""
from __future__ import annotations

PERSONAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS profile_facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL DEFAULT 'preference', -- preference / goal / constraint
    content     TEXT NOT NULL,
    evidence    TEXT NOT NULL DEFAULT '',           -- 出处：会话/日期/用户原话
    confidence  REAL NOT NULL DEFAULT 0.5,
    status      TEXT NOT NULL DEFAULT 'active',     -- active / archived
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profile_kind ON profile_facts (kind, status);

CREATE TABLE IF NOT EXISTS project_refs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    repo_path    TEXT NOT NULL DEFAULT '',          -- 只存路径，不复制仓库内容
    handoff_path TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active',    -- active / paused / archived
    next_step    TEXT NOT NULL DEFAULT '',
    risk         TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'news',      -- news / word / price / stock / custom
    cadence      TEXT NOT NULL DEFAULT 'daily',     -- daily / weekly
    at_time      TEXT NOT NULL DEFAULT '07:30',
    sources_json TEXT NOT NULL DEFAULT '[]',
    last_run     TEXT NOT NULL DEFAULT '',
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (topic, kind)
);

CREATE TABLE IF NOT EXISTS daily_cards (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    day          TEXT NOT NULL,
    domain       TEXT NOT NULL DEFAULT 'life',      -- learn / work / life
    title        TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL DEFAULT '{}',
    read_at      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    UNIQUE (day, domain, title)
);
CREATE INDEX IF NOT EXISTS idx_daily_cards_day ON daily_cards (day, domain);
"""
