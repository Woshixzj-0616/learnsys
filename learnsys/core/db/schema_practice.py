"""实践经验库：记录「和 AI / 工具打交道时，下次还想记得的事」。

不是技术知识库，也没有标准答案；只强制三格：
场景（我在干什么）/ 坑或有效点（实际发生了什么）/ 下次（下次先做什么）。
技术原因 `why` 与证据 `evidence` 可选，通常由 AI 起草时补。
工程专业不按 FSRS 每天复习，按搜索与「最近用到」取用。
"""
from __future__ import annotations

PRACTICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS practice_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    title      TEXT NOT NULL,
    scene      TEXT NOT NULL DEFAULT '',
    pitfall    TEXT NOT NULL DEFAULT '',
    next_time  TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT 'pitfall',   -- pitfall / good_practice
    why        TEXT NOT NULL DEFAULT '',          -- 可选：技术原因，AI 起草时补
    evidence   TEXT NOT NULL DEFAULT '',          -- 可选：命令 / 日志 / 链接
    tags       TEXT NOT NULL DEFAULT '',
    project_id INTEGER NOT NULL DEFAULT 0,        -- 可选：关联 project_refs
    source     TEXT NOT NULL DEFAULT 'manual',    -- ask / agent_task / code / manual
    source_id  TEXT NOT NULL DEFAULT '',
    used_count INTEGER NOT NULL DEFAULT 0,
    last_used  TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'active',    -- active / archived
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_practice_recent
    ON practice_notes (status, updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_practice_project
    ON practice_notes (project_id, status);
CREATE INDEX IF NOT EXISTS idx_practice_tags
    ON practice_notes (tags);
"""
