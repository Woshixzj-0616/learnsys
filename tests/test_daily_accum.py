# -*- coding: utf-8 -*-
"""每日积累：生成、冻结、轮换、状态、连续天数、翻译词入生词本。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import config, store
from learnsys.services.cet6 import daily_accum
from learnsys.train import content as train_content

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

    def _writing_keys(self, day):
        return {row["ref_key"] for row in daily_accum._writing_payloads(day)}

    def test_writing_rotates_without_overlap(self):
        days = [f"2026-11-{number:02d}" for number in range(1, 13)]
        for before, after in zip(days, days[1:]):
            self.assertFalse(self._writing_keys(before) & self._writing_keys(after),
                             f"{before} 和 {after} 的写作句型重复")

    def test_writing_covers_all_patterns_in_one_cycle(self):
        days = [f"2026-11-{number:02d}" for number in range(1, 25)]
        keys = [self._writing_keys(day) for day in days]
        self.assertEqual(len(set().union(*keys)), 48)
        for before, after in zip(keys, keys[1:]):
            self.assertFalse(before & after)

    def test_theme_terms_rotate_without_overlap(self):
        days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]
        keys = []
        for day in days:
            rows = daily_accum._translation_payloads(self.conn, day)
            keys.append({row["ref_key"] for row in rows
                         if row["payload"]["tag"] == "主题词"})
            # 模拟当天已生成：第二天生成时必须跳过这些词。
            for row in rows:
                store.add_accum(self.conn, day=day, kind="translation",
                                ref_key=row["ref_key"], payload=row["payload"])
        for key in keys:
            self.assertEqual(len(key), 4)
        for before, after in zip(keys, keys[1:]):
            self.assertFalse(before & after,
                             "相邻两天的主题词重复")

    def test_writing_payload_is_pattern_with_example(self):
        rows = daily_accum._writing_payloads("2026-10-31")
        self.assertEqual(len(rows), 2)
        for row in rows:
            payload = row["payload"]
            self.assertTrue(payload["pattern"].strip())
            self.assertTrue(payload["zh"].strip())
            self.assertTrue(payload["example"].strip())
            self.assertTrue(payload["example_zh"].strip())
            self.assertNotIn("en", payload)

    def test_translation_mixes_phrases_and_themes(self):
        rows = daily_accum._translation_payloads(self.conn, "2026-11-02")
        self.assertEqual(len(rows), 8)
        tags = [row["payload"]["tag"] for row in rows]
        self.assertEqual(tags.count("高频短语"), 4)
        self.assertEqual(tags.count("主题词"), 4)
        # 4 个主题词必须来自不同篇目，不能又变成一天一个主题。
        theme_ids = [row["payload"]["source_id"].split(":")[0]
                     for row in rows if row["payload"]["tag"] == "主题词"]
        self.assertEqual(len(set(theme_ids)), 4)
        self.assertIn("红包", [row["zh"] for row in
                               train_content.translation_phrases()])

    def test_translation_skips_active_vocab(self):
        store.add_vocab(self.conn, word="red envelopes", meaning="红包")
        rows = daily_accum._translation_payloads(self.conn, "2026-11-18")
        self.assertEqual(len(rows), 8)
        words = {row["payload"]["en"] for row in rows}
        self.assertNotIn("red envelopes", words)

    def test_translation_skips_history(self):
        first = daily_accum._translation_payloads(self.conn, "2026-11-18")
        for row in first:
            store.add_accum(self.conn, day="2026-11-18", kind="translation",
                            ref_key=row["ref_key"], payload=row["payload"])
        second = daily_accum._translation_payloads(self.conn, "2026-11-18")
        self.assertEqual(len(second), 8)
        self.assertFalse({row["ref_key"] for row in first}
                         & {row["ref_key"] for row in second})

    def test_add_term_to_vocab_removes_accum_state(self):
        today = daily_accum._today()
        daily_accum.ensure_day(self.conn, today)
        item = next(row for row in store.accum_items(self.conn, today)
                    if row["kind"] == "translation")
        self.assertIsNotNone(
            store.get_review_state(self.conn, "accum", item["id"]))
        daily_accum.add_term_to_vocab(self.conn, item["id"])
        self.assertIsNone(
            store.get_review_state(self.conn, "accum", item["id"]))

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
