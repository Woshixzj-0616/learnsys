"""P26.1 Agent 中枢表：任务与事件。拼进 `schema.SCHEMA`。"""
from __future__ import annotations

AGENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    workspace   TEXT NOT NULL DEFAULT '',
    mode        TEXT NOT NULL DEFAULT 'read',
    status      TEXT NOT NULL DEFAULT 'queued',
    exit_code   INTEGER,
    created_at  TEXT NOT NULL,
    started_at  TEXT NOT NULL DEFAULT '',
    ended_at    TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    output_path TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT '',
    cost_usd    REAL NOT NULL DEFAULT 0,
    usage_json  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_created
    ON agent_tasks (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status
    ON agent_tasks (status, agent);
CREATE TABLE IF NOT EXISTS agent_task_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    seq     INTEGER NOT NULL,
    ts      TEXT NOT NULL,
    kind    TEXT NOT NULL DEFAULT 'text',
    text    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_task_events_task
    ON agent_task_events (task_id, seq);
CREATE TABLE IF NOT EXISTS agent_approvals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL,
    seq          INTEGER NOT NULL DEFAULT 0,
    tool         TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL DEFAULT 'other',
    target       TEXT NOT NULL DEFAULT '',
    summary      TEXT NOT NULL DEFAULT '',
    preview      TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT NOT NULL,
    decided_at   TEXT NOT NULL DEFAULT '',
    reason       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_approvals_task
    ON agent_approvals (task_id, id);
CREATE INDEX IF NOT EXISTS idx_agent_approvals_status
    ON agent_approvals (status, task_id);
"""
