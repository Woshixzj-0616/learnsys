# -*- coding: utf-8 -*-
"""P27.1 schema：12 版建表、幂等、旧库只加表不加改。"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest

from learnsys import store
from learnsys.core import db as core_db


PERSONAL_TABLES = ("profile_facts", "project_refs", "subscriptions",
                   "daily_cards", "life_items")


class TestSchemaPersonal(unittest.TestCase):
    def test_new_db_has_personal_tables_and_current_version(self):
        conn = store.connect(":memory:")
        self.addCleanup(conn.close)
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in PERSONAL_TABLES:
            self.assertIn(table, names)
        self.assertEqual(
            conn.execute("PRAGMA user_version").fetchone()[0],
            core_db.SCHEMA_VERSION)
        self.assertEqual(core_db.SCHEMA_VERSION, 15)

    def test_connect_twice_keeps_rows_and_does_not_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "learning.db"
            first = store.connect(path)
            try:
                store.upsert_fact(first, content="回答用中文")
                store.upsert_card(first, day="2026-10-29", domain="life",
                                  title="早睡", content={"text": "23:00 前"})
            finally:
                first.close()

            second = store.connect(path)
            try:
                self.assertEqual(
                    second.execute("PRAGMA user_version").fetchone()[0],
                    core_db.SCHEMA_VERSION)
                self.assertEqual(
                    second.execute("SELECT COUNT(*) FROM profile_facts")
                    .fetchone()[0], 1)
                self.assertEqual(
                    second.execute("SELECT COUNT(*) FROM daily_cards")
                    .fetchone()[0], 1)
            finally:
                second.close()

    def test_old_v11_db_upgrades_without_touching_rows(self):
        """旧库（user_version=11）升级到当前版本：只加表/加列，旧行原样保留。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "learning.db"
            old = sqlite3.connect(str(path))
            old.executescript("""
                CREATE TABLE asks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    ms INTEGER,
                    backend TEXT
                );
                INSERT INTO asks (ts, question, answer, ms, backend)
                VALUES ('2026-10-20 10:00:00', '旧问题一', '旧答案一', 10, 'old');
                INSERT INTO asks (ts, question, answer, ms, backend)
                VALUES ('2026-10-21 10:00:00', '旧问题二', '旧答案二', 20, 'old');
                PRAGMA user_version = 11;
            """)
            old.commit()
            old.close()

            conn = core_db.connect(path)
            try:
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    core_db.SCHEMA_VERSION)
                rows = conn.execute(
                    "SELECT question, answer FROM asks ORDER BY id").fetchall()
                self.assertEqual(rows, [("旧问题一", "旧答案一"),
                                       ("旧问题二", "旧答案二")])
                names = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")}
                for table in PERSONAL_TABLES:
                    self.assertIn(table, names)
            finally:
                conn.close()

    def test_wrong_items_has_code_columns(self):
        conn = store.connect(":memory:")
        self.addCleanup(conn.close)
        columns = {row[1] for row in conn.execute(
            "PRAGMA table_info(wrong_items)")}
        for name in ("code", "language", "error_type", "test_cases"):
            self.assertIn(name, columns, f"wrong_items 缺代码题字段 {name}")

    def test_v12_db_adds_code_columns_without_losing_rows(self):
        """P28 只给 wrong_items 加列；旧题原样保留，新字段默认空串。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "learning.db"
            old = sqlite3.connect(str(path))
            old.executescript("""
                CREATE TABLE wrong_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_id TEXT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL DEFAULT '',
                    my_answer TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    auto INTEGER NOT NULL DEFAULT 0,
                    review_stage INTEGER NOT NULL DEFAULT 0,
                    last_review TEXT NOT NULL DEFAULT '',
                    mastered INTEGER NOT NULL DEFAULT 0,
                    material_id INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO wrong_items (ts, question, answer, tags)
                VALUES ('2026-10-20 10:00:00', '旧题', '旧答案', '旧标签');
                PRAGMA user_version = 12;
            """)
            old.commit()
            old.close()

            conn = core_db.connect(path)
            try:
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0], 15)
                row = conn.execute(
                    "SELECT question, answer, tags, code, language, "
                    "error_type, test_cases FROM wrong_items").fetchone()
                self.assertEqual(row, ("旧题", "旧答案", "旧标签", "", "", "", ""))
            finally:
                conn.close()

    def test_personal_columns_match_contract(self):
        conn = store.connect(":memory:")
        self.addCleanup(conn.close)
        expected = {
            "profile_facts": {"kind", "content", "evidence", "confidence",
                              "status", "created_at", "updated_at"},
            "project_refs": {"name", "repo_path", "handoff_path", "status",
                             "next_step", "risk", "updated_at"},
            "subscriptions": {"topic", "kind", "cadence", "at_time",
                              "sources_json", "last_run", "enabled",
                              "created_at", "updated_at"},
            "daily_cards": {"day", "domain", "title", "content_json",
                            "read_at", "created_at"},
            "life_items": {"title", "kind", "due_date", "status", "note",
                           "value", "done_at", "created_at", "updated_at"},
        }
        for table, columns in expected.items():
            actual = {row[1] for row in conn.execute(
                f"PRAGMA table_info({table})")}
            self.assertTrue(columns <= actual,
                            f"{table} 缺列：{columns - actual}")


if __name__ == "__main__":
    unittest.main()
