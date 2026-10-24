"""v2 统一库：schema、中文检索、按天迁移、幂等、日期过滤。"""
from __future__ import annotations

import datetime
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.services import study
from learnsys.core import db as core_db
from learnsys.core.db import connection as db_connection


def make_day_db(root: pathlib.Path, day: datetime.date,
                question: str = "二叉树怎么遍历") -> pathlib.Path:
    folder = root / f"{day.year}.{day.month}.{day.day}"
    path = folder / "learnsys.db"
    conn = store.connect(path)
    sid = store.start_session(conn)
    store.add_transcript(conn, sid, f"{day} 10:00:00", f"{day} 10:00:45",
                         "今天讲了二叉树的遍历")
    store.add_ask(conn, question, "前序、中序、后序", 120, "test")
    store.add_window_event_at(conn, sid, f"{day} 10:00:00", "code.exe", "数据结构")
    conn.close()
    return path


class TestUnifiedSchema(unittest.TestCase):
    def test_schema_has_v2_tables(self):
        conn = store.connect(":memory:")
        self.addCleanup(conn.close)
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        for name in ("asks", "transcripts", "conversations", "messages",
                     "cet6_events", "events", "search_idx", "migrated_sources"):
            self.assertIn(name, names)

    def test_chinese_fts_and_short_query_fallback(self):
        conn = store.connect(":memory:")
        self.addCleanup(conn.close)
        store.add_ask(conn, "今天讲了二叉树的遍历", "前序、中序、后序", 100, "test")
        long_hits = core_db.search(conn, "二叉树", limit=5)
        self.assertTrue(long_hits, "3 字中文应该能走 FTS 命中")
        short_hits = core_db.search(conn, "栈", limit=5)
        self.assertEqual(short_hits, [], "没有的内容不该凭空命中")
        store.add_ask(conn, "栈和队列的区别", "后进先出 / 先进先出", 80, "test")
        self.assertTrue(core_db.search(conn, "栈", limit=5), "1 字应该退回 LIKE 命中")


class TestSchemaVersion(unittest.TestCase):
    def test_new_db_records_current_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = core_db.connect(pathlib.Path(tmp) / "learning.db")
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(version, core_db.SCHEMA_VERSION)
            finally:
                conn.close()

    def test_second_connect_skips_ddl_and_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "learning.db"
            core_db.connect(path).close()

            statements: list[str] = []
            real_connect = sqlite3.connect

            def traced(*args, **kwargs):
                conn = real_connect(*args, **kwargs)
                conn.set_trace_callback(statements.append)
                return conn

            with mock.patch.object(db_connection.sqlite3, "connect",
                                   side_effect=traced):
                conn = db_connection.connect(path)
            try:
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    core_db.SCHEMA_VERSION)
            finally:
                conn.close()

            writes = [sql for sql in statements if sql.strip().upper().startswith(
                ("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE"))]
            self.assertEqual(writes, [], f"第二次连接不该再写库：{writes}")
            self.assertTrue(any("user_version" in sql.lower() for sql in statements),
                            "第二次连接应该先读 user_version 再决定")

    def test_old_db_upgrades_and_records_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "learning.db"
            old = sqlite3.connect(str(path))
            old.executescript("""
                CREATE TABLE asks (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
                    ms INTEGER, backend TEXT);
                INSERT INTO asks (ts, question, answer, ms, backend)
                VALUES ('2026-09-01 10:00:00', '旧问题', '旧答案', 10, 'old');
            """)
            old.commit()
            old.close()

            conn = core_db.connect(path)
            try:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(asks)")}
                for column in ("kind", "first_ms", "conversation_id", "model"):
                    self.assertIn(column, cols)
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    core_db.SCHEMA_VERSION)
                row = conn.execute(
                    "SELECT question, answer FROM asks").fetchone()
                self.assertEqual(row, ("旧问题", "旧答案"))
            finally:
                conn.close()


class TestMigration(unittest.TestCase):
    def test_migrates_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            day1 = datetime.date(2026, 10, 15)
            day2 = datetime.date(2026, 10, 16)
            make_day_db(root, day1, "链表怎么插入")
            make_day_db(root, day2, "二叉树怎么遍历")
            target = root / "learning.db"

            first = core_db.migrate_from_v1(root, target)
            self.assertEqual(len(first["sources"]), 2)
            conn = store.connect(target)
            try:
                counts = core_db.counts(conn)
                self.assertEqual(counts["asks"], 2)
                self.assertEqual(counts["transcripts"], 2)
                self.assertEqual(counts["sessions"], 2)
                self.assertEqual(counts["window_events"], 2)
            finally:
                conn.close()

            second = core_db.migrate_from_v1(root, target)
            self.assertEqual(len(second["sources"]), 0)
            self.assertEqual(len(second["skipped"]), 2)
            conn = store.connect(target)
            try:
                self.assertEqual(core_db.counts(conn)["asks"], 2)
            finally:
                conn.close()

    def test_old_asks_without_new_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            folder = root / "2026.9.1"
            folder.mkdir()
            old = sqlite3.connect(str(folder / "learnsys.db"))
            old.executescript("""
                CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL, ended_at TEXT);
                CREATE TABLE asks (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
                    ms INTEGER, backend TEXT);
                INSERT INTO asks (ts, question, answer, ms, backend)
                VALUES ('2026-09-01 10:00:00', '旧问题', '旧答案', 10, 'old');
            """)
            old.commit()
            old.close()
            target = root / "learning.db"
            core_db.migrate_from_v1(root, target)
            conn = store.connect(target)
            try:
                row = conn.execute(
                    "SELECT question, answer, kind, starred FROM asks").fetchone()
                self.assertEqual(row[0], "旧问题")
                self.assertEqual(row[2], "text")
                self.assertEqual(row[3], 0)
            finally:
                conn.close()

    def test_storage_dbs_prefers_unified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            make_day_db(root, datetime.date(2026, 10, 15))
            self.assertEqual(len(study.storage_dbs(root)), 1)
            (root / "learning.db").write_bytes(b"")
            chosen = study.storage_dbs(root)
            self.assertEqual(len(chosen), 1)
            self.assertEqual(chosen[0][1].name, "learning.db")


class TestDayFilters(unittest.TestCase):
    def test_focus_stats_and_recent_asks_filter_by_day(self):
        conn = store.connect(":memory:")
        self.addCleanup(conn.close)
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        sid_today = store.start_session(conn)
        store.add_window_event_at(conn, sid_today, f"{today} 10:00:00", "code.exe", "今天")
        store.add_window_event_at(conn, sid_today, f"{today} 10:10:00", "chrome.exe", "今天")
        sid_old = store.start_session(conn)
        store.add_window_event_at(conn, sid_old, f"{yesterday} 10:00:00", "game.exe", "昨天")
        conn.execute("UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
                     (f"{today} 10:00:00", f"{today} 10:20:00", sid_today))
        conn.execute("UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
                     (f"{yesterday} 10:00:00", f"{yesterday} 10:10:00", sid_old))
        store.add_ask(conn, "今天的问题", "答", 10, "test")
        # 把今天的问答时间改成今天、再插一条昨天的
        conn.execute("UPDATE asks SET ts = ? WHERE question = ?",
                     (f"{today} 09:00:00", "今天的问题"))
        conn.execute(
            "INSERT INTO asks (ts, question, answer) VALUES (?, ?, ?)",
            (f"{yesterday} 09:00:00", "昨天的问题", "答"))
        conn.commit()

        stats = store.focus_stats(conn, day=today.isoformat())
        self.assertGreater(stats["分钟"], 0)
        self.assertEqual(
            [name for name, _ in stats["程序"]], ["code", "chrome"])

        rows = store.recent_asks(conn, limit=10, day=today.isoformat())
        self.assertEqual([row[1] for row in rows], ["今天的问题"])


if __name__ == "__main__":
    unittest.main()
