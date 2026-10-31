# -*- coding: utf-8 -*-
"""每日积累：生成、冻结、轮换、状态、连续天数、翻译词入生词本。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import config, store
from learnsys.services import daily_accum

PAPER = "卷一"
SECTION = "Section A 长对话"
ITEM = "Conversation 1"

NOTES = [
    "combat没有听出，听成come back了",
    "sameness没有听出",
    "lodging没有听出，不知道意思",
    "subtle没有听出",
    "vicious没有听出",
    "rest理解成休息，infects听成effects",
]


class DailyAccumTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.conn = store.connect(self.root / "learning.db")
        self.addCleanup(self.conn.close)
        self.patch = mock.patch.object(config, "cet6_dir",
                                       return_value=self.root / "none")
        self.patch.start()
        self.addCleanup(self.patch.stop)
        store.upsert_cet6_progress(
            self.conn, paper_id="p1", paper_title=PAPER,
            section=SECTION, item=ITEM,
            rows=[{"sentence": index + 1,
                   "en": f"This is sentence number {index + 1} with combat."}
                  for index in range(len(NOTES))],
            done=[])
        for index, note in enumerate(NOTES, start=1):
            self.conn.execute(
                "UPDATE cet6_progress SET note = ? WHERE paper_id = 'p1' "
                "AND section = ? AND item = ? AND sentence = ?",
                (note, SECTION, ITEM, index))
        self.conn.commit()

    def test_today_summary_generates_expected_counts(self):
        data = daily_accum.today_summary(self.conn)
        self.assertEqual(data["counts"]["writing"]["total"], 2)
        self.assertEqual(data["counts"]["translation"]["total"], 8)
        self.assertGreaterEqual(data["counts"]["pron"]["total"], 5)
        self.assertEqual(data["total"], data["counts"]["writing"]["total"]
                         + data["counts"]["translation"]["total"]
                         + data["counts"]["pron"]["total"])

    def test_day_is_frozen(self):
        first = daily_accum.list_day(self.conn)
        second = daily_accum.list_day(self.conn)
        self.assertEqual([item["id"] for item in first["items"]["writing"]],
                         [item["id"] for item in second["items"]["writing"]])
        self.assertEqual(first["total"], second["total"])

    def test_writing_rotates_next_day(self):
        today = daily_accum._writing_payloads("2026-10-31")
        tomorrow = daily_accum._writing_payloads("2026-11-01")
        self.assertNotEqual([row["payload"]["en"] for row in today],
                            [row["payload"]["en"] for row in tomorrow])

    def test_mark_and_streak(self):
        data = daily_accum.list_day(self.conn)
        for group in data["items"].values():
            for item in group:
                daily_accum.mark(self.conn, item["id"], "read")
        summary = daily_accum.summary(self.conn, data["day"])
        self.assertEqual(summary["done"], summary["total"])
        self.assertEqual(summary["streak"], 1)

    def test_read_all_completes_day(self):
        daily_accum.list_day(self.conn)
        summary = daily_accum.mark_all(self.conn)
        self.assertEqual(summary["done"], summary["total"])
        self.assertEqual(summary["streak"], 1)

    def test_master_pron_updates_pool(self):
        data = daily_accum.list_day(self.conn)
        item = data["items"]["pron"][0]
        daily_accum.mark(self.conn, item["id"], "mastered")
        pool = store.pron_candidates(self.conn, since="2000-01-01", limit=50)
        ids = {row["id"] for row in pool}
        self.assertNotIn(item["payload"]["pron_id"], ids)

    def test_term_to_vocab(self):
        data = daily_accum.list_day(self.conn)
        item = data["items"]["translation"][0]
        result = daily_accum.add_term_to_vocab(self.conn, item["id"])
        self.assertIn("vocab", result)
        words = [row["word"] for row in store.list_vocab(self.conn)["items"]]
        self.assertIn(item["payload"]["en"], words)
        again = daily_accum.add_term_to_vocab(self.conn, item["id"])
        self.assertFalse(again["created"])

    def test_history_contains_today(self):
        daily_accum.list_day(self.conn)
        days = daily_accum.history(self.conn)["days"]
        self.assertTrue(any(row["total"] > 0 for row in days))

    def test_mark_invalid_status(self):
        data = daily_accum.list_day(self.conn)
        with self.assertRaises(ValueError):
            daily_accum.mark(self.conn, data["items"]["writing"][0]["id"], "bogus")


if __name__ == "__main__":
    unittest.main()
