# -*- coding: utf-8 -*-
"""每日积累产复习卡：启用日、两个 tab 的来源、评分落库。"""
from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.services import review

EPOCH = store.DAILY_REVIEW_EPOCH.isoformat()
BEFORE = (store.DAILY_REVIEW_EPOCH - dt.timedelta(days=1)).isoformat()
TODAY = dt.date.today().isoformat()


class ReviewAccumTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        conn.close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        self.conn = store.connect()
        self.addCleanup(self.conn.close)
        self.writing_id = store.add_accum(
            self.conn, day=EPOCH, kind="writing", ref_key="pattern:t1",
            payload={"zh": "引出观点", "pattern": "There is a growing awareness that...",
                     "example": "There is a growing awareness that...",
                     "example_zh": "越来越多的人意识到……"})
        self.phrase_id = store.add_accum(
            self.conn, day=EPOCH, kind="translation", ref_key="phrase:t1",
            payload={"zh": "高铁", "en": "high-speed rail", "note": "交通类"})
        self.old_id = store.add_accum(
            self.conn, day=BEFORE, kind="writing", ref_key="pattern:old",
            payload={"zh": "旧内容", "pattern": "old pattern"})

    def test_seed_respects_epoch(self):
        store.seed_review_states(self.conn, today=TODAY)
        ids = {row[0] for row in self.conn.execute(
            "SELECT item_id FROM review_state WHERE item_type = 'accum'")}
        self.assertIn(self.writing_id, ids)
        self.assertIn(self.phrase_id, ids)
        self.assertNotIn(self.old_id, ids)

    def test_queue_splits_writing_and_translation(self):
        sentence = review.queue(self.conn, kind="sentence", today=TODAY)
        self.assertEqual([item["item_id"] for item in sentence["items"]
                          if item["item_type"] == "accum"], [self.writing_id])
        card = sentence["items"][0]
        self.assertEqual(card["question"], "引出观点")
        self.assertIn("There is a growing awareness", card["answer"])
        self.assertEqual(card["source"], "daily")

        word = review.queue(self.conn, kind="word", today=TODAY)
        accum = [item for item in word["items"] if item["item_type"] == "accum"]
        self.assertEqual([item["item_id"] for item in accum], [self.phrase_id])
        self.assertEqual(accum[0]["word"], "高铁")
        self.assertEqual(accum[0]["meaning"], "high-speed rail")

    def test_due_counts_include_accum(self):
        store.seed_review_states(self.conn, today=TODAY)   # 每日积累生成时会先播种
        counts = review.due_counts(self.conn, today=TODAY)
        self.assertGreaterEqual(counts["sentence"], 1)
        self.assertGreaterEqual(counts["word"], 1)

    def test_accum_not_blocked_by_wrong_backlog(self):
        for index in range(10):
            store.add_wrong_item(
                self.conn, question=f"旧错题 {index}", answer="参考",
                source="translation")
        store.seed_review_states(self.conn, today=TODAY)
        self.conn.execute(
            "UPDATE review_state SET due = ? WHERE item_type = 'wrong'", (TODAY,))
        self.conn.commit()

        data = review.queue(self.conn, kind="sentence", limit=10, today=TODAY)
        self.assertEqual(data["count"], 10)
        self.assertEqual(data["items"][0]["item_type"], "accum")
        self.assertEqual(data["new_remaining"], 10)   # 每日积累不占旧错题配额

    def test_ensure_day_seeds_today_cards(self):
        from learnsys.services.cet6 import daily_accum
        daily_accum.ensure_day(self.conn, TODAY)
        counts = review.due_counts(self.conn, today=TODAY)
        self.assertGreaterEqual(counts["sentence"], 1)
        self.assertGreaterEqual(counts["word"], 1)

    def test_rating_accum_card(self):
        result = review.review(self.conn, "accum", self.phrase_id, 3)
        self.assertEqual(result["state"]["state"], "review")
        self.assertNotEqual(result["next_review"], "")
        row = self.conn.execute(
            "SELECT state FROM review_state WHERE item_type = 'accum' "
            "AND item_id = ?", (self.phrase_id,)).fetchone()
        self.assertEqual(row[0], "review")
        log = self.conn.execute(
            "SELECT count(*) FROM review_log WHERE item_type = 'accum' "
            "AND item_id = ?", (self.phrase_id,)).fetchone()
        self.assertEqual(log[0], 1)


if __name__ == "__main__":
    unittest.main()
