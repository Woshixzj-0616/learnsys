"""记忆单表模型：去重键、合并、状态、profile_facts 兼容视图与迁移。"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest

from learnsys import store
from learnsys.core import db as core_db
from learnsys.core.textkey import content_key


class TestContentKey(unittest.TestCase):
    def test_normalizes_whitespace_and_punctuation(self):
        self.assertEqual(content_key("回答 一律 用中文。"), content_key("回答一律用中文"))

    def test_keeps_chinese_and_is_stable(self):
        self.assertEqual(content_key("听力先看题"), "听力先看题")

    def test_nonempty_symbols_get_hash(self):
        key = content_key("！！！")
        self.assertTrue(key.startswith("sha1:"))
        self.assertNotEqual(key, content_key("？？？"))


class TestMemoryModel(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_columns_and_view(self):
        columns = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(agent_memories)")}
        for name in ("content_key", "scope", "evidence", "confidence",
                     "source", "pinned", "batch_id", "archived_reason"):
            self.assertIn(name, columns)
        kind = self.conn.execute(
            "SELECT type FROM sqlite_master WHERE name = 'profile_facts'"
        ).fetchone()
        self.assertEqual(kind, ("view",))

    def test_add_dedupes_by_normalized_content(self):
        first, created = store.add_memory(self.conn, "回答用中文。")
        second, created2 = store.add_memory(self.conn, "回答 用 中文")
        self.assertTrue(created)
        self.assertFalse(created2)
        self.assertEqual(first, second)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM agent_memories").fetchone()[0], 1)

    def test_duplicate_merges_evidence_and_confidence(self):
        memory_id, _ = store.add_memory(
            self.conn, "六级听力先看题", evidence="profile:a.md#L1",
            confidence=0.6)
        store.add_memory(
            self.conn, "六级听力先看题。", evidence="archive:s/m2",
            confidence=0.9)
        row = store.get_memory(self.conn, memory_id)
        self.assertIn("profile:a.md#L1", row["evidence"])
        self.assertIn("archive:s/m2", row["evidence"])
        self.assertEqual(row["confidence"], 0.9)

    def test_candidate_then_promote(self):
        memory_id, _ = store.add_memory(
            self.conn, "以后先复习再刷新题", status="candidate", confidence=0.6)
        self.assertEqual(store.list_memories(self.conn, status="candidate")[0]["id"],
                         memory_id)
        self.assertTrue(store.promote_memory(self.conn, memory_id))
        self.assertEqual(store.get_memory(self.conn, memory_id)["status"], "active")

    def test_mark_used_updates_counter(self):
        memory_id, _ = store.add_memory(self.conn, "示例代码用 C++")
        store.mark_used(self.conn, [memory_id])
        row = store.get_memory(self.conn, memory_id)
        self.assertEqual(row["use_count"], 1)
        self.assertTrue(row["last_used_at"])

    def test_profile_facts_adapter_uses_same_rows(self):
        fact = store.upsert_fact(self.conn, content="目标：十二月过六级",
                                 kind="goal", confidence=0.9)
        self.assertTrue(fact["id"])
        self.assertEqual(store.list_facts(self.conn, kind="goal")[0]["content"],
                         "目标：十二月过六级")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM agent_memories").fetchone()[0], 1)


class TestProfileFactsMigration(unittest.TestCase):
    def test_old_table_is_copied_then_replaced_by_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "learning.db"
            old = sqlite3.connect(str(path))
            old.executescript("""
                CREATE TABLE profile_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL DEFAULT 'preference',
                    content TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO profile_facts
                    (kind, content, evidence, confidence, status, created_at, updated_at)
                VALUES ('preference', '旧画像：喜欢先看原理', 'legacy.md#L3',
                        0.8, 'active', '2026-10-01 10:00:00', '2026-10-01 10:00:00');
                PRAGMA user_version = 20;
            """)
            old.commit()
            old.close()

            conn = core_db.connect(path)
            try:
                row = conn.execute(
                    "SELECT content, evidence, confidence, source FROM agent_memories"
                ).fetchone()
                self.assertEqual(row[0], "旧画像：喜欢先看原理")
                self.assertEqual(row[1], "legacy.md#L3")
                self.assertEqual(row[2], 0.8)
                self.assertEqual(row[3], "profile_facts")
                kind = conn.execute(
                    "SELECT type FROM sqlite_master WHERE name = 'profile_facts'"
                ).fetchone()
                self.assertEqual(kind, ("view",))
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM profile_facts").fetchone()[0], 1)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
