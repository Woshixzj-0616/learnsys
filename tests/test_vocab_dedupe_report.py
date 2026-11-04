# -*- coding: utf-8 -*-
"""生词本去重：归档旧英文-英文术语卡，中文词头原地转英文词头。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import store
from tools import vocab_dedupe_report as tool


class VocabDedupeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(pathlib.Path(self.tmp.name) / "learning.db")
        self.addCleanup(self.conn.close)

    def add_raw(self, word, meaning):
        cur = self.conn.execute(
            "INSERT INTO vocab_items "
            "(word, normalized, meaning, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', 'translation', "
            "'2026-11-03 11:57:32', '2026-11-03 11:57:32')",
            (word, word.lower(), meaning))
        self.conn.commit()
        return int(cur.lastrowid)

    def test_archive_junk_and_reorient_chinese_headword(self):
        junk, _ = store.add_vocab(
            self.conn, word="spring paper", meaning="spring couplets",
            source="translation")
        chinese_id = self.add_raw("春联", "spring couplets")
        store.save_review_state(
            self.conn, "vocab", chinese_id, state="review", due="2026-11-07",
            reps=1)
        store.add_vocab(self.conn, word="porcelain", meaning="瓷器")

        report = tool.collect(self.conn)
        self.assertEqual([row["id"] for row in report["junk"]], [junk["id"]])
        self.assertEqual([row["item"]["id"] for row in report["swaps"]],
                         [chinese_id])

        applied = tool.apply(self.conn, report)
        self.assertEqual(applied, {"archived": 1, "reoriented": 1, "merged": 0})
        item = store.get_vocab(self.conn, chinese_id)
        self.assertEqual(item["id"], chinese_id)
        self.assertEqual(item["word"], "spring couplets")
        self.assertEqual(item["meaning"], "春联")
        self.assertIsNotNone(store.get_review_state(self.conn, "vocab", chinese_id))
        self.assertEqual(len(store.list_vocab(self.conn)["items"]), 2)
        self.assertEqual(len(store.list_vocab(self.conn, status="archived")["items"]), 1)

    def test_second_run_is_idempotent(self):
        store.add_vocab(self.conn, word="spring paper",
                        meaning="spring couplets", source="translation")
        self.add_raw("春联", "spring couplets")
        tool.apply(self.conn, tool.collect(self.conn))
        again = tool.collect(self.conn)
        self.assertEqual(again["junk"], [])
        self.assertEqual(again["swaps"], [])
        self.assertEqual(tool.apply(self.conn, again),
                         {"archived": 0, "reoriented": 0, "merged": 0})


if __name__ == "__main__":
    unittest.main()
