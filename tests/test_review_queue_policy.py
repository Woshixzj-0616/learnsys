# -*- coding: utf-8 -*-
"""复习队列编排：今日积累、旧积累不饿死、遗忘风险排序、同日稳定。"""
from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.services import review

TODAY = dt.date.today()
TODAY_TEXT = TODAY.isoformat()
YESTERDAY = (TODAY - dt.timedelta(days=1)).isoformat()
TEN_DAYS_AGO = (TODAY - dt.timedelta(days=10)).isoformat()


class ReviewQueuePolicyTest(unittest.TestCase):
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

    def _accum(self, day: str, kind: str, ref: str) -> int:
        return store.add_accum(
            self.conn, day=day, kind=kind, ref_key=ref,
            payload={"zh": ref, "en": ref, "pattern": ref})

    def _wrong(self, question: str, source: str = "translation") -> int:
        item_id, _ = store.add_wrong_item(
            self.conn, question=question, answer="参考", source=source)
        return item_id

    def _vocab(self, word: str) -> int:
        item, _ = store.add_vocab(
            self.conn, word=word, meaning="词义", source="cet6")
        return item["id"]

    def test_today_accum_comes_before_old_accum_and_wrong(self):
        self._accum(YESTERDAY, "writing", "old-pattern")
        today_id = self._accum(TODAY_TEXT, "writing", "today-pattern")
        for index in range(5):
            self._wrong(f"旧错题 {index}")

        body = review.queue(self.conn, kind="sentence", limit=10, today=TODAY_TEXT)
        self.assertEqual(body["items"][0]["item_id"], today_id)
        self.assertEqual(body["items"][0]["accum_day"], TODAY_TEXT)

    def test_old_accum_does_not_starve_vocab_reviews(self):
        for index in range(20):
            self._accum(YESTERDAY, "translation", f"old-phrase-{index}")
        store.seed_review_states(self.conn, today=TODAY_TEXT)
        for index in range(10):
            item_id = self._vocab(f"word{index}")
            store.save_review_state(
                self.conn, "vocab", item_id, state="review", due=TODAY_TEXT,
                stability=5.0, difficulty=5.0, reps=2, lapses=0,
                last_review=f"{YESTERDAY} 09:00:00", scheduled_days=3,
                elapsed_days=1)

        body = review.queue(self.conn, kind="word", limit=10, today=TODAY_TEXT)
        kinds = [item["item_type"] for item in body["items"]]
        self.assertGreaterEqual(kinds.count("vocab"), 4,
                                "旧积累最多占复习位一半，生词必须轮得到")
        self.assertGreaterEqual(kinds.count("accum"), 1)

    def test_forgetting_risk_puts_unstable_card_first(self):
        low = self._wrong("低稳定度")
        high = self._wrong("高稳定度")
        store.save_review_state(
            self.conn, "wrong", low, state="review", due=TODAY_TEXT,
            stability=2.0, difficulty=5.0, reps=3, lapses=0,
            last_review=f"{TEN_DAYS_AGO} 09:00:00", scheduled_days=3,
            elapsed_days=10)
        store.save_review_state(
            self.conn, "wrong", high, state="review", due=TODAY_TEXT,
            stability=100.0, difficulty=5.0, reps=3, lapses=0,
            last_review=f"{YESTERDAY} 09:00:00", scheduled_days=3,
            elapsed_days=1)

        body = review.queue(self.conn, kind="sentence", limit=10, today=TODAY_TEXT)
        self.assertEqual(body["items"][0]["item_id"], low)

    def test_queue_order_is_stable_within_the_same_day(self):
        for index in range(6):
            self._wrong(f"题 {index}")
        first = review.queue(self.conn, kind="sentence", limit=10, today=TODAY_TEXT)
        second = review.queue(self.conn, kind="sentence", limit=10, today=TODAY_TEXT)
        self.assertEqual([item["item_id"] for item in first["items"]],
                         [item["item_id"] for item in second["items"]])


if __name__ == "__main__":
    unittest.main()
