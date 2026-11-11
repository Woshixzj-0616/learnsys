# -*- coding: utf-8 -*-
"""生词本口径：只留单词/术语/专有名词，多词改错归档。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from tools import vocab_scope_report


class VocabScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        store.connect(self.db_path).close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        self.conn = store.connect()
        self.addCleanup(self.conn.close)
        self.word_id = store.add_vocab(
            self.conn, word="capital", meaning="首都｜拼写",
            source="sentence")[0]["id"]
        self.term_id = store.add_vocab(
            self.conn, word="electronic payment", meaning="电子支付",
            source="translation")[0]["id"]
        self.proper_id = store.add_vocab(
            self.conn, word="the Chinese Dream", meaning="中国梦",
            source="translation")[0]["id"]
        self.phrase_id = store.add_vocab(
            self.conn, word="financial support", meaning="经济支持",
            source="sentence")[0]["id"]
        self.expression_id = store.add_vocab(
            self.conn, word="stay up late to see the old year out",
            meaning="守岁", source="translation")[0]["id"]
        self.daily_id = store.add_vocab(
            self.conn, word="高铁", meaning="high-speed rail",
            source="daily")[0]["id"]

    def test_collect_splits_words_terms_and_multiword_corrections(self):
        report = vocab_scope_report.collect(self.conn)
        keep_ids = {row["id"] for row in report["keep"]}
        drop_ids = {row["id"] for row in report["drop"]}
        self.assertIn(self.word_id, keep_ids)
        self.assertIn(self.term_id, keep_ids)
        self.assertIn(self.proper_id, keep_ids)
        self.assertIn(self.phrase_id, drop_ids)
        self.assertIn(self.expression_id, drop_ids)
        self.assertNotIn(self.daily_id, keep_ids | drop_ids)   # 每日积累不动

    def test_apply_archives_only_multiword_corrections(self):
        report = vocab_scope_report.collect(self.conn)
        archived = vocab_scope_report.apply(self.conn, report)
        self.assertEqual(archived, 2)
        active = {row["id"] for row in store.list_vocab(self.conn)["items"]}
        self.assertIn(self.word_id, active)
        self.assertIn(self.term_id, active)
        self.assertIn(self.proper_id, active)
        self.assertNotIn(self.phrase_id, active)
        self.assertNotIn(self.expression_id, active)
        self.assertEqual(store.get_vocab(self.conn, self.phrase_id)["status"],
                         "archived")
        self.assertEqual(store.get_vocab(self.conn, self.daily_id)["status"],
                         "active")


if __name__ == "__main__":
    unittest.main()
