"""学习工作台 v2 的统一数据库。

为什么从「一天一个库」改成「一个库」：
- 复盘、薄弱点、学习曲线、跨天检索都要求把历史放在一起；
- 会话跨零点不再断成两个库；
- 迁移、备份、统计都简单。

v1 的按天库**不删不改**：迁移只读源库，写进 `learning.db`；
`migrated_sources` 记录迁过哪些，重复跑不会重复插入。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3
import threading

from learnsys import config

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
    ts              TEXT NOT NULL
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

_LOCK = threading.Lock()


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path=None) -> sqlite3.Connection:
    """打开统一库（缺省 = `config.db_path()`），建表 + 迁移 + FTS。"""
    target = pathlib.Path(path) if path else config.db_path()
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    _ensure_fts(conn)
    _import_legacy_starred(conn)
    return conn


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
    conn.commit()


def _ensure_fts(conn: sqlite3.Connection) -> None:
    """FTS5 trigram 可用就用；不可用退回普通表（LIKE 查询）。"""
    try:
        conn.executescript(FTS_SCHEMA)
        return
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS search_idx "
        "(body TEXT, module TEXT, ref_id INTEGER, ts TEXT)")
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
    except sqlite3.Error:
        pass
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
    except sqlite3.Error:
        pass


def fts_ready(conn: sqlite3.Connection) -> bool:
    """查 sqlite_master 判断 search_idx 是不是 FTS5 虚表。

    ⚠️ 不能按 `id(conn)` 缓存：Python 的 id 会被回收复用，旧连接的结论
    会错误地套到新连接上。查一次 sqlite_master 很便宜，别省。
    """
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'search_idx'").fetchone()
    except sqlite3.Error:
        return False
    return bool(row and row[0] and "fts5" in str(row[0]).lower())


def index_row(conn: sqlite3.Connection, module: str, ref_id, ts: str, body: str) -> None:
    """把一条记录写进检索索引（先删同一条，避免重复）。"""
    body = (body or "").strip()
    if not body:
        return
    try:
        with _LOCK:
            conn.execute("DELETE FROM search_idx WHERE module = ? AND ref_id = ?",
                         (module, ref_id))
            conn.execute(
                "INSERT INTO search_idx (body, module, ref_id, ts) VALUES (?, ?, ?, ?)",
                (body, module, ref_id, ts))
            conn.commit()
    except sqlite3.Error:
        pass          # 索引是锦上添花，失败不能拖垮写入


def search(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    """跨天检索。FTS 可用且关键词够长走 MATCH，否则退回 LIKE。

    trigram 对 3 字以上的中文片段最有效；两个字（如「栈」）走 LIKE 更稳。
    """
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(int(limit or 20), 100))
    rows: list[tuple] = []
    if fts_ready(conn) and len(query) >= 3:
        try:
            rows = conn.execute(
                "SELECT module, ref_id, ts, body FROM search_idx "
                "WHERE search_idx MATCH ? ORDER BY rank LIMIT ?",
                (query, limit)).fetchall()
        except sqlite3.Error:
            rows = []
    if not rows:
        pattern = f"%{query}%"
        asks = conn.execute(
            "SELECT 'ask', id, ts, question || char(10) || answer FROM asks "
            "WHERE question LIKE ? OR answer LIKE ? ORDER BY ts DESC LIMIT ?",
            (pattern, pattern, limit)).fetchall()
        transcripts = conn.execute(
            "SELECT 'transcript', id, ts_start, text FROM transcripts "
            "WHERE text LIKE ? ORDER BY ts_start DESC LIMIT ?",
            (pattern, limit)).fetchall()
        frames = conn.execute(
            "SELECT 'frame', path, ts, text FROM frame_text "
            "WHERE text LIKE ? ORDER BY ts DESC LIMIT ?",
            (pattern, limit)).fetchall()
        rows = sorted(asks + transcripts + frames, key=lambda row: str(row[2]), reverse=True)[:limit]
    return [
        {"module": row[0], "ref_id": row[1], "ts": row[2], "text": str(row[3] or "")[:600]}
        for row in rows
    ]


def counts(conn: sqlite3.Connection) -> dict:
    def one(sql: str) -> int:
        try:
            return int(conn.execute(sql).fetchone()[0] or 0)
        except sqlite3.Error:
            return 0
    return {
        "asks": one("SELECT COUNT(*) FROM asks"),
        "transcripts": one("SELECT COUNT(*) FROM transcripts"),
        "window_events": one("SELECT COUNT(*) FROM window_events"),
        "sessions": one("SELECT COUNT(*) FROM sessions"),
        "frame_text": one("SELECT COUNT(*) FROM frame_text"),
        "cet6_events": one("SELECT COUNT(*) FROM cet6_events"),
        "messages": one("SELECT COUNT(*) FROM messages"),
        "wrong_items": one("SELECT COUNT(*) FROM wrong_items"),
        "materials": one("SELECT COUNT(*) FROM materials"),
    }


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
