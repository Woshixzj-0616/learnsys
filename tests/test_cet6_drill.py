# -*- coding: utf-8 -*-
"""六级专项听写：词级差异、队列、自动建卡、统计。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.services import cet6_drill


def seed(conn):
    store.upsert_cet6_progress(
        conn, paper_id="p1", paper_title="卷一",
        section="Section C 讲座/讲话", item="Recording 1",
        rows=[{"sentence": 1, "en": "For 60 years, cells divide forever.",
               "note": "60听成6了，cells也没听出", "plays": 12}],
        done=[1])
    store.upsert_cet6_progress(
        conn, paper_id="p1", paper_title="卷一",
        section="Section A 长对话", item="Conversation 1",
        rows=[{"sentence": 1, "en": "Hello there, nice to meet you.",
               "note": "", "plays": 0}], done=[])


class DrillServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(pathlib.Path(self.tmp.name) / "learning.db")
        self.addCleanup(self.conn.close)
        self.cet6_patch = mock.patch.object(
            cet6_drill.config, "cet6_dir",
            return_value=pathlib.Path(self.tmp.name) / "none")
        self.cet6_patch.start()
        self.addCleanup(self.cet6_patch.stop)
        seed(self.conn)

    def test_diff_marks_missed_content_word(self):
        diff = cet6_drill.diff_answer(
            "For 60 years, cells divide forever.",
            "For 6 years, cells divide forever.")
        missed = [item["token"] for item in diff["missed"]]
        self.assertIn("60", missed)
        self.assertLess(diff["score"], 1.0)
        self.assertTrue(any(part["miss"] for part in diff["parts"]))

    def test_diff_ignores_punctuation_and_case(self):
        diff = cet6_drill.diff_answer(
            "For 60 years, cells divide forever.",
            "for 60 years cells divide forever")
        self.assertEqual(diff["score"], 1.0)
        self.assertEqual(diff["missed"], [])

    def test_queue_has_note_and_coverage_without_leaking_note(self):
        data = cet6_drill.queue(self.conn, limit=4)
        self.assertEqual(data["count"], 2)
        sources = {item["source"] for item in data["items"]}
        self.assertEqual(sources, {"note", "coverage"})
        for item in data["items"]:
            self.assertNotIn("note", item, "提交前不能把笔记（可能含答案）下发")
            self.assertIn("audio_url", item)

    def test_attempt_creates_cards_and_dedupes(self):
        payload = {"paper_id": "p1", "section": "Section C 讲座/讲话",
                   "item": "Recording 1", "sentence": 1,
                   "answer": "For 6 years, cells divide forever.",
                   "duration_s": 20}
        first = cet6_drill.attempt(self.conn, payload)
        self.assertGreaterEqual(first["cards_created"], 1)
        self.assertLess(first["score"], 1.0)
        cards = store.wrong_items(
            self.conn, source="cet6_dictation", limit=50)
        self.assertTrue(any(card["answer"] == "60" for card in cards))
        card = next(card for card in cards if card["answer"] == "60")
        self.assertIn("____", card["question"])
        self.assertTrue(card["next_review"])
        self.assertTrue(card["tags"].startswith("听辨"))

        second = cet6_drill.attempt(self.conn, payload)
        self.assertEqual(second["cards_created"], 0)
        self.assertEqual(len(store.wrong_items(
            self.conn, source="cet6_dictation", limit=50)), len(cards))

    def test_empty_answer_does_not_create_cards(self):
        result = cet6_drill.attempt(self.conn, {
            "paper_id": "p1", "section": "Section C 讲座/讲话",
            "item": "Recording 1", "sentence": 1, "answer": ""})
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["cards_created"], 0)
        self.assertEqual(store.wrong_items(
            self.conn, source="cet6_dictation", limit=50), [])

    def test_attempt_missing_sentence(self):
        with self.assertRaises(LookupError):
            cet6_drill.attempt(self.conn, {
                "paper_id": "p1", "section": "Section C 讲座/讲话",
                "item": "Recording 1", "sentence": 99, "answer": "x"})

    def test_stats_aggregates_attempts(self):
        for answer in ("For 6 years, cells divide forever.",
                       "For 60 years, cells divide forever."):
            cet6_drill.attempt(self.conn, {
                "paper_id": "p1", "section": "Section C 讲座/讲话",
                "item": "Recording 1", "sentence": 1, "answer": answer})
        data = cet6_drill.stats(self.conn, days=30)
        self.assertEqual(data["total_attempts"], 2)
        self.assertEqual(data["sentences"], 1)
        self.assertGreater(data["cards_added"], 0)
        self.assertIn("Section C 讲座/讲话", data["by_section"])
        self.assertTrue(any(row["token"] == "60" for row in data["top_missed"]))

    def test_drill_table_exists(self):
        names = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("cet6_drill_attempts", names)


if __name__ == "__main__":
    unittest.main()
