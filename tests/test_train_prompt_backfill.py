# -*- coding: utf-8 -*-
"""整篇翻译卡正面回填工具：中文题面、学生英文到背面、幂等。"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest

from learnsys import store

TOOL = pathlib.Path(__file__).resolve().parent.parent / "tools" / "train_prompt_backfill.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("train_prompt_backfill_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TrainPromptBackfillTest(unittest.TestCase):
    def setUp(self):
        self.tool = _load_tool()
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.student = ("The Spring Festival is the most important traditional "
                        "festival in China.")
        alignment = [{"segment": 1, "quote": self.student}]
        self.conn.execute(
            "INSERT INTO train_submissions (kind, prompt_id, mode, text, status, "
            "band_json, created_at, updated_at) VALUES "
            "('translation', 't01', 'timed', ?, 'reviewed', ?, '', '')",
            (self.student, json.dumps({"alignment": alignment},
                                      ensure_ascii=False)))
        self.card_id, _ = store.add_wrong_item(
            self.conn, source="translation",
            source_id="translation:t01:abcdef1234",
            question=self.student, answer="**必改**\n- x", note="1 处必改")
        self.conn.commit()

    def test_collect_and_apply(self):
        report = self.tool.collect(self.conn)
        self.assertEqual(len(report["plans"]), 1)
        plan = report["plans"][0]
        self.assertTrue(plan["question"].startswith("春节是中国最重要的传统节日"))
        self.assertEqual(plan["source_id"], "translation:t01:seg1")
        applied = self.tool.apply(self.conn, report)
        self.assertEqual(applied["updated"], 1)
        card = store.get_wrong_item(self.conn, self.card_id)
        self.assertTrue(card["question"].startswith("春节是中国最重要的传统节日"))
        self.assertEqual(card["my_answer"], self.student)
        self.assertEqual(card["source_id"], "translation:t01:seg1")
        # 第二次不会再把它当旧卡。
        again = self.tool.collect(self.conn)
        self.assertEqual(again["plans"], [])

    def test_sentence_cards_are_ignored(self):
        store.add_wrong_item(
            self.conn, source="translation", source_id="sentence:x001",
            question="这是中文原句。", answer="x")
        report = self.tool.collect(self.conn)
        self.assertEqual(len(report["plans"]), 1)


if __name__ == "__main__":
    unittest.main()
