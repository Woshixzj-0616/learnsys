# -*- coding: utf-8 -*-
"""迁移工具：碎片错题合并成整句卡，非词条生词归档。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.train import content
from tools import train_sentence_migrate as tool

TEXT = "As city people grow, housing and traffic face new pressure."
PAYLOAD = {
    "conclusion": "有偏差",
    "must_fix": [
        {"type": "用词", "quote": "city people",
         "fix": "the urban population", "why": "用词不准"},
        {"type": "搭配", "quote": "face new pressure",
         "fix": "are under new pressure", "why": "更自然"},
    ],
    "suggestions": [],
    "minimal_fix": TEXT,
}


class TrainSentenceMigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(pathlib.Path(self.tmp.name) / "learning.db")
        self.addCleanup(self.conn.close)

    def seed(self):
        self.conn.execute(
            "INSERT INTO train_submissions "
            "(kind, prompt_id, mode, status, text, band_json, created_at, updated_at) "
            "VALUES ('translation', 'x001', 'sentence', 'reviewed', ?, ?, "
            "'2026-11-04 10:00:00', '2026-11-04 10:00:00')",
            (TEXT, json.dumps(PAYLOAD, ensure_ascii=False)))
        self.conn.commit()
        first, _ = store.add_wrong_item(
            self.conn, question="改译：city people",
            answer="the urban population", my_answer="city people",
            tags="用词 翻译", note="用词不准", source="translation",
            source_id="sentence:x001:x001:1:aaa", auto=True)
        second, _ = store.add_wrong_item(
            self.conn, question="改译：face new pressure",
            answer="are under new pressure", my_answer="face new pressure",
            tags="搭配 翻译", note="更自然", source="translation",
            source_id="sentence:x001:x001:2:bbb", auto=True)
        store.save_review_state(
            self.conn, "wrong", second, state="review", due="2026-11-06",
            stability=3.0, difficulty=5.0, reps=3, lapses=1,
            last_review="2026-11-04", scheduled_days=2, elapsed_days=2)
        store.add_vocab(
            self.conn, word="Schools should", meaning="语法：主谓一致",
            context="一句一译：x ｜ 我当时写：School should", source="sentence")
        store.add_vocab(
            self.conn, word="accommodation", meaning="拼写：多了一个字母",
            context="一句一译：x ｜ 我当时写：accommendation",
            source="sentence")
        return first, second

    def test_cards_merge_and_review_state_moves(self):
        first, second = self.seed()
        cards = tool.collect_cards(self.conn)
        self.assertEqual(len(cards["groups"]), 1)
        group = cards["groups"][0]
        self.assertEqual(group["new_id"], "sentence:x001")
        self.assertEqual(sorted(group["card_ids"]), sorted([first, second]))
        self.assertEqual(group["survivor"], first)

        tool.apply(self.conn, cards, {"decisions": []})
        wrong = store.wrong_items(self.conn, source="translation")
        self.assertEqual(len(wrong), 1)
        card = wrong[0]
        self.assertEqual(card["source_id"], "sentence:x001")
        self.assertEqual(card["question"], content.sentence("x001")["zh"])
        self.assertEqual(card["my_answer"], TEXT)
        self.assertIn("the urban population", card["answer"])
        self.assertIn("are under new pressure", card["answer"])
        self.assertEqual(store.get_review_state(self.conn, "wrong", first)["reps"], 3)

    def test_vocab_cleanup_archives_only_non_lexical(self):
        self.seed()
        vocab = tool.collect_vocab(self.conn)
        archived = {row["word"] for row in vocab["decisions"]
                    if row["action"] == "archive"}
        kept = {row["word"] for row in vocab["decisions"]
                if row["action"] == "keep"}
        self.assertEqual(archived, {"Schools should"})
        self.assertIn("accommodation", kept)

        tool.apply(self.conn, {"groups": [], "skipped": [], "cards": 0}, vocab)
        active = {row["word"] for row in store.list_vocab(self.conn)["items"]}
        self.assertEqual(active, {"accommodation"})
        archived_rows = {row["word"] for row in
                         store.list_vocab(self.conn, status="archived")["items"]}
        self.assertEqual(archived_rows, {"Schools should"})

    def test_second_run_is_idempotent(self):
        self.seed()
        cards = tool.collect_cards(self.conn)
        tool.apply(self.conn, cards, {"decisions": []})
        again = tool.collect_cards(self.conn)
        self.assertEqual(len(again["groups"]), 1)
        self.assertEqual(again["groups"][0]["card_ids"],
                         [again["groups"][0]["survivor"]])
        tool.apply(self.conn, again, {"decisions": []})
        self.assertEqual(len(store.wrong_items(self.conn, source="translation")), 1)


if __name__ == "__main__":
    unittest.main()
