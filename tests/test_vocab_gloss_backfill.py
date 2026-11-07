# -*- coding: utf-8 -*-
"""历史生词补词义：只挑解释型释义，旧释义保留为错因备注。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from tools import vocab_gloss_backfill as tool

GLOSSES = {"vary greatly": "差异很大", "capital": "资本",
           "across provinces": "跨省"}


def fake_complete(prompt, **_kwargs):
    return json.dumps(GLOSSES, ensure_ascii=False), "", {}


class VocabGlossBackfillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(pathlib.Path(self.tmp.name) / "learning.db")
        self.addCleanup(self.conn.close)
        store.add_vocab(self.conn, word="vary greatly",
                        meaning="搭配错：different 不直接与 variety 搭配",
                        source="sentence")
        store.add_vocab(self.conn, word="capital",
                        meaning="拼写错误｜captial → capital", source="sentence")
        store.add_vocab(self.conn, word="across provinces",
                        meaning="跨省｜介词短语", source="daily")
        store.add_vocab(self.conn, word="manual word",
                        meaning="手动释义", source="manual")
        self.patch = mock.patch.object(tool.agent, "complete", fake_complete)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_collect_only_explanation_meanings(self):
        report = tool.collect(self.conn)
        self.assertEqual({row["word"] for row in report["rows"]},
                         {"vary greatly", "capital"})

    def test_apply_prepends_gloss_and_keeps_note(self):
        report = tool.collect(self.conn)
        proposals = tool.propose(report["rows"])
        self.assertEqual(len(proposals["proposals"]), 2)
        tool.apply(self.conn, proposals)
        rows = {row["word"]: row for row in store.list_vocab(self.conn)["items"]}
        self.assertEqual(rows["vary greatly"]["meaning"],
                         "差异很大｜搭配错：different 不直接与 variety 搭配")
        self.assertEqual(rows["capital"]["meaning"],
                         "资本｜拼写错误｜captial → capital")
        self.assertEqual(rows["across provinces"]["meaning"], "跨省｜介词短语")
        self.assertEqual(rows["manual word"]["meaning"], "手动释义")

    def test_second_run_is_idempotent(self):
        tool.apply(self.conn, tool.propose(tool.collect(self.conn)["rows"]))
        again = tool.collect(self.conn)
        self.assertEqual(again["rows"], [])


if __name__ == "__main__":
    unittest.main()
