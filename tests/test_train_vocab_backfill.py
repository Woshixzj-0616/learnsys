# -*- coding: utf-8 -*-
"""六级训练历史问题回填：过滤纯格式/过长/已有，保留一句一译与整篇翻译。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from learnsys import store
from tools import train_vocab_backfill as tool


class TrainVocabBackfillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(pathlib.Path(self.tmp.name) / "learning.db")
        self.addCleanup(self.conn.close)
        store.add_vocab(self.conn, word="the urban population", meaning="城市人口")

    def add_submission(self, kind, mode, prompt_id, payload):
        self.conn.execute(
            "INSERT INTO train_submissions "
            "(kind, prompt_id, mode, status, band_json, created_at, updated_at) "
            "VALUES (?, ?, ?, 'reviewed', ?, '2026-11-03 10:00:00', "
            "'2026-11-03 10:00:00')",
            (kind, prompt_id, mode, json.dumps(payload, ensure_ascii=False)))
        self.conn.commit()

    def seed(self):
        self.add_submission("translation", "sentence", "x010", {"must_fix": [
            {"type": "用词", "quote": "city people",
             "fix": "the urban population", "why": "用词不准"},
            {"type": "用词", "quote": "have  an insight",
             "fix": "have an insight", "why": "语法：多余空格"},
            {"type": "用词", "quote": "the losing questions",
             "fix": "the danger of dying out", "why": "误译"},
        ]})
        self.add_submission("translation", "timed", "t01", {"errors": [
            {"type": "术语", "quote": "spring paper",
             "fix": "spring couplets", "why": "“春联”术语错误"},
            {"type": "用词", "quote": "x", "fix": "y" * 130, "why": "太长"},
        ]})

    def test_collect_filters_and_apply_adds(self):
        self.seed()
        report = tool.collect(self.conn)
        self.assertEqual([row["fix"] for row in report["rows"]],
                         ["the danger of dying out", "spring couplets"])
        self.assertEqual(len(report["skipped"]), 3)
        applied = tool.apply(self.conn, report)
        self.assertEqual(applied, {"added": 2, "merged": 0})

        rows = {row["word"]: row for row in store.list_vocab(self.conn)["items"]}
        sentence = rows["the danger of dying out"]
        self.assertTrue(sentence["meaning"].startswith("误译｜"))
        self.assertIn("the losing questions → the danger of dying out",
                      sentence["meaning"])
        self.assertIn("一句一译", sentence["context"])
        self.assertEqual(sentence["paper_title"], "技能专项")
        translation = rows["spring couplets"]
        self.assertEqual(translation["meaning"], "“春联”术语错误")
        self.assertIn("spring paper → spring couplets", translation["context"])
        self.assertEqual(translation["paper_title"], "春节与年夜饭")

    def test_second_run_is_idempotent(self):
        self.seed()
        tool.apply(self.conn, tool.collect(self.conn))
        again = tool.collect(self.conn)
        self.assertEqual(again["rows"], [])
        self.assertEqual(tool.apply(self.conn, again), {"added": 0, "merged": 0})


if __name__ == "__main__":
    unittest.main()
