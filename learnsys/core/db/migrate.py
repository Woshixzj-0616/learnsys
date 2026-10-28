"""迁移：老库补列、旧收藏一次性搬入、v1 按天库只读迁进统一库。"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3

from learnsys import diagnostics

from .connection import connect, counts, now
from .fts import index_row


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """老库补列（CREATE IF NOT EXISTS 不会给已存在的表加字段）。"""
    have = {row[1] for row in conn.execute("PRAGMA table_info(asks)").fetchall()}
    for column, ddl in (
        ("kind", "TEXT"),
        ("image_path", "TEXT"),
        ("thread", "TEXT"),
        ("starred", "INTEGER DEFAULT 0"),
        ("review_stage", "INTEGER DEFAULT 0"),
        ("last_remind", "TEXT"),
        ("conversation_id", "INTEGER"),
        ("provider", "TEXT"),
        ("model", "TEXT"),
        ("first_ms", "INTEGER"),
    ):
        if column not in have:
            conn.execute(f"ALTER TABLE asks ADD COLUMN {column} {ddl}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asks_conversation ON asks (conversation_id)")
    wrong_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(wrong_items)").fetchall()}
    if wrong_cols and "material_id" not in wrong_cols:
        conn.execute(
            "ALTER TABLE wrong_items ADD COLUMN material_id INTEGER NOT NULL DEFAULT 0")
    if wrong_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wrong_material ON wrong_items (material_id)")
    run_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(agent_runs)").fetchall()}
    for column, ddl in (
        ("tool_count", "INTEGER NOT NULL DEFAULT 0"),
        ("model_calls", "INTEGER NOT NULL DEFAULT 0"),
        ("error_count", "INTEGER NOT NULL DEFAULT 0"),
        ("cost", "REAL NOT NULL DEFAULT 0"),
        ("currency", "TEXT NOT NULL DEFAULT ''"),
    ):
        if run_cols and column not in run_cols:
            conn.execute(f"ALTER TABLE agent_runs ADD COLUMN {column} {ddl}")
    task_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(agent_tasks)").fetchall()}
    for column, ddl in (
        ("route_json", "TEXT NOT NULL DEFAULT ''"),
        ("timeout_s", "INTEGER NOT NULL DEFAULT 0"),
        ("depends_on", "INTEGER NOT NULL DEFAULT 0"),
        ("result_text", "TEXT NOT NULL DEFAULT ''"),
        ("runner", "TEXT NOT NULL DEFAULT ''"),
        ("heartbeat_at", "TEXT NOT NULL DEFAULT ''"),
    ):
        if task_cols and column not in task_cols:
            conn.execute(f"ALTER TABLE agent_tasks ADD COLUMN {column} {ddl}")
    message_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(messages)").fetchall()}
    if message_cols and "result_id" not in message_cols:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN result_id INTEGER NOT NULL DEFAULT 0")
    session_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(sessions)").fetchall()}
    for column, ddl in (
        ("kind", "TEXT NOT NULL DEFAULT 'video'"),
        ("title", "TEXT NOT NULL DEFAULT ''"),
        ("video_path", "TEXT NOT NULL DEFAULT ''"),
        ("video_bytes", "INTEGER NOT NULL DEFAULT 0"),
        ("duration_ms", "INTEGER NOT NULL DEFAULT 0"),
        ("thumb_path", "TEXT NOT NULL DEFAULT ''"),
        ("slides_dir", "TEXT NOT NULL DEFAULT ''"),
        ("material_id", "INTEGER NOT NULL DEFAULT 0"),
        ("analysis_result_id", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if session_cols and column not in session_cols:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} {ddl}")
    frame_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(frame_text)").fetchall()}
    if frame_cols and "session_id" not in frame_cols:
        conn.execute(
            "ALTER TABLE frame_text ADD COLUMN session_id INTEGER NOT NULL DEFAULT 0")
    if frame_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_frame_text_session "
            "ON frame_text (session_id, ts)")
    cet6_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(cet6_events)").fetchall()}
    if cet6_cols and "dedupe_key" not in cet6_cols:
        conn.execute(
            "ALTER TABLE cet6_events ADD COLUMN dedupe_key TEXT NOT NULL DEFAULT ''")
    if cet6_cols:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_cet6_dedupe "
            "ON cet6_events (dedupe_key) WHERE dedupe_key <> ''")
    conversation_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(conversations)").fetchall()}
    for column, ddl in (
        ("origin", "TEXT NOT NULL DEFAULT 'ask'"),
        ("recording_id", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if conversation_cols and column not in conversation_cols:
            conn.execute(f"ALTER TABLE conversations ADD COLUMN {column} {ddl}")
    if conversation_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_origin "
            "ON conversations (origin, recording_id, updated_at)")
    service_index = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' "
        "AND name = 'idx_service_results_key'").fetchone()
    if service_index and "WHERE" not in str(service_index[0] or "").upper():
        conn.execute("DROP INDEX idx_service_results_key")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_service_results_key "
            "ON service_results (kind, target_type, target_id, scope, "
            "context_hash, prompt_version) WHERE status <> 'superseded'")
    conn.commit()


def _import_starred_rows(conn: sqlite3.Connection) -> int:
    """把 `asks.starred=1` 补进统一错题本（`INSERT OR IGNORE`，可重复跑）。

    v2 之前的「收藏」只存在 `asks.starred`。错题本改成独立表后，这一列只当
    历史快照：这里只负责搬一次，之后代码不再读写它。
    """
    moved = 0
    try:
        rows = conn.execute(
            "SELECT id, ts, question, answer FROM asks WHERE starred = 1").fetchall()
        for ask_id, ts, question, answer in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO wrong_items "
                "(ts, source, source_id, question, answer, auto) "
                "VALUES (?, 'ask', ?, ?, ?, 0)",
                (ts or now(), f"ask:{ask_id}", question or "", answer or ""))
            moved += 1 if cur.rowcount else 0
        conn.commit()
    except sqlite3.Error as exc:
        diagnostics.log_swallow("迁移旧收藏到错题本", exc)
    return moved


def _import_legacy_starred(conn: sqlite3.Connection) -> None:
    """首次打开统一库时做一次旧收藏迁移；meta 记过就不再跑，删掉的题不会复活。"""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'wrongbook_imported_at'").fetchone()
        if row:
            return
        _import_starred_rows(conn)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('wrongbook_imported_at', ?)",
            (now(),))
        conn.commit()
    except sqlite3.Error as exc:
        diagnostics.log_swallow("旧收藏迁移标记", exc)


# ---- v1 按天库 → v2 单库 ----

def _day_dbs(data_root: pathlib.Path) -> list[tuple[dt.date, pathlib.Path]]:
    """数据根下所有「YYYY.M.D/learnsys.db」，新→旧。"""
    out: list[tuple[dt.date, pathlib.Path]] = []
    if not data_root.is_dir():
        return out
    for db in data_root.glob("*/learnsys.db"):
        parts = db.parent.name.split(".")
        try:
            day = dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            continue
        out.append((day, db))
    out.sort(key=lambda pair: pair[0], reverse=True)
    return out


def _table_rows(source: sqlite3.Connection, sql: str) -> list[tuple]:
    try:
        return source.execute(sql).fetchall()
    except sqlite3.Error:
        return []


def migrate_from_v1(data_root: pathlib.Path, target: pathlib.Path,
                    *, verbose: bool = False) -> dict:
    """把按天库只读迁进统一库。返回报告；重复跑会跳过已迁的源。"""
    data_root = pathlib.Path(data_root)
    target = pathlib.Path(target)
    report = {"sources": [], "skipped": [], "counts": {}, "target": str(target)}
    conn = connect(target)
    try:
        done = {row[0] for row in conn.execute(
            "SELECT path FROM migrated_sources").fetchall()}
        for day, source_path in _day_dbs(data_root):
            source_key = str(source_path.resolve())
            if source_key in done:
                report["skipped"].append(source_key)
                continue
            if source_path.resolve() == target.resolve():
                continue
            try:
                source = sqlite3.connect(str(source_path))
            except sqlite3.Error:
                continue
            try:
                source_counts = _migrate_one(conn, source, source_key)
            finally:
                source.close()
            conn.execute(
                "INSERT OR REPLACE INTO migrated_sources (path, migrated_at, counts_json) "
                "VALUES (?, ?, ?)",
                (source_key, now(), json.dumps(source_counts, ensure_ascii=False)))
            # 首次升级时 connect() 可能先于旧库迁移把 meta 标成已迁 —— 这里再补一次，
            # 只补这次新迁进来的 starred 行；重复跑 migrate 时 sources 已跳过，不会复活删除项。
            if source_counts.get("asks"):
                _import_starred_rows(conn)
            conn.commit()
            report["sources"].append({"path": source_key, "counts": source_counts})
            if verbose:
                print(f"迁移 {day.isoformat()}：{source_counts}")
        report["counts"] = counts(conn)
    finally:
        conn.close()
    return report


def _migrate_one(conn: sqlite3.Connection, source: sqlite3.Connection,
                 source_key: str) -> dict:
    """迁一个按天库；返回这个库迁了多少行。"""
    session_map: dict[int, int] = {}
    moved = {"sessions": 0, "window_events": 0, "transcripts": 0,
             "asks": 0, "frame_text": 0}

    for sid, started, ended in _table_rows(
            source, "SELECT id, started_at, COALESCE(ended_at, '') FROM sessions"):
        cur = conn.execute(
            "INSERT INTO sessions (started_at, ended_at) VALUES (?, ?)",
            (started, ended or None))
        session_map[int(sid)] = int(cur.lastrowid)
        moved["sessions"] += 1

    for sid, ts, process, title in _table_rows(
            source, "SELECT session_id, ts, process, title FROM window_events"):
        new_sid = session_map.get(int(sid))
        if new_sid is None:
            continue
        conn.execute(
            "INSERT INTO window_events (session_id, ts, process, title) VALUES (?, ?, ?, ?)",
            (new_sid, ts, process, title))
        moved["window_events"] += 1

    for sid, ts_start, ts_end, text in _table_rows(
            source, "SELECT session_id, ts_start, ts_end, text FROM transcripts"):
        new_sid = session_map.get(int(sid))
        if new_sid is None:
            continue
        cur = conn.execute(
            "INSERT INTO transcripts (session_id, ts_start, ts_end, text) VALUES (?, ?, ?, ?)",
            (new_sid, ts_start, ts_end, text))
        index_row(conn, "transcript", int(cur.lastrowid), str(ts_start), str(text))
        moved["transcripts"] += 1

    # 老库的 asks 可能缺列（v1.4 之前）—— 按实际列名读，缺的走默认值。
    try:
        cursor = source.execute("SELECT * FROM asks ORDER BY id")
        ask_names = [item[0] for item in (cursor.description or [])]
        ask_rows = cursor.fetchall()
    except sqlite3.Error:
        ask_names, ask_rows = [], []
    for values in ask_rows:
        row = dict(zip(ask_names, values))
        ts = row.get("ts") or now()
        question = row.get("question") or ""
        answer = row.get("answer") or ""
        backend = row.get("backend") or ""
        cur = conn.execute(
            "INSERT INTO asks (ts, question, answer, ms, backend, kind, image_path, thread, "
            "starred, review_stage, last_remind, provider, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, question, answer, row.get("ms"), backend,
             row.get("kind") or "text", row.get("image_path") or "",
             row.get("thread") or "", int(row.get("starred") or 0),
             int(row.get("review_stage") or 0), row.get("last_remind"),
             backend, backend))
        index_row(conn, "ask", int(cur.lastrowid), str(ts),
                  f"{question}\n{answer}")
        moved["asks"] += 1

    for path, ts, text in _table_rows(
            source, "SELECT path, ts, text FROM frame_text"):
        conn.execute(
            "INSERT OR REPLACE INTO frame_text (path, ts, text) VALUES (?, ?, ?)",
            (path, ts, text))
        index_row(conn, "frame", path, str(ts), str(text))
        moved["frame_text"] += 1

    conn.commit()
    return moved
