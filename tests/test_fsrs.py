# -*- coding: utf-8 -*-
"""FSRS-5 纯函数：初始间隔、递增、遗忘、同日复习。"""
from __future__ import annotations

import datetime as dt
import unittest

from learnsys.services import fsrs

NOW = dt.datetime(2026, 10, 21, 9, 0, 0)


class FsrsTest(unittest.TestCase):
    def test_new_good_gives_three_days(self):
        state = fsrs.schedule(None, 3, NOW)
        self.assertEqual(state["state"], "review")
        self.assertEqual(state["scheduled_days"], 3)
        self.assertEqual(state["due"], "2026-10-24")
        self.assertAlmostEqual(state["stability"], 3.173, places=2)
        self.assertAlmostEqual(state["difficulty"], 7.1949, places=2)
        self.assertEqual(state["reps"], 1)
        self.assertEqual(state["lapses"], 0)

    def test_new_again_is_one_day_and_learning(self):
        state = fsrs.schedule(None, 1, NOW)
        self.assertEqual(state["state"], "learning")
        self.assertEqual(state["scheduled_days"], 1)
        self.assertEqual(state["due"], "2026-10-22")

    def test_rating_moves_interval(self):
        hard = fsrs.schedule(None, 2, NOW)["scheduled_days"]
        good = fsrs.schedule(None, 3, NOW)["scheduled_days"]
        easy = fsrs.schedule(None, 4, NOW)["scheduled_days"]
        self.assertLess(hard, good)
        self.assertLess(good, easy)

    def test_consecutive_good_intervals_grow(self):
        first = fsrs.schedule(None, 3, NOW)
        second = fsrs.schedule(first, 3, dt.datetime(2026, 10, 24, 9))
        third = fsrs.schedule(second, 3, dt.datetime(2026, 10, 31, 9))
        self.assertGreater(second["scheduled_days"], first["scheduled_days"])
        self.assertGreater(third["scheduled_days"], second["scheduled_days"])
        self.assertGreater(third["stability"], second["stability"])

    def test_forget_drops_stability_and_counts_lapse(self):
        first = fsrs.schedule(None, 3, NOW)
        second = fsrs.schedule(first, 3, dt.datetime(2026, 10, 24, 9))
        forgotten = fsrs.schedule(second, 1, dt.datetime(2026, 11, 5, 9))
        self.assertLess(forgotten["stability"], second["stability"])
        self.assertEqual(forgotten["lapses"], 1)
        self.assertEqual(forgotten["scheduled_days"], 1)
        self.assertEqual(forgotten["state"], "learning")

    def test_same_day_review_uses_short_term_formula(self):
        first = fsrs.schedule(None, 3, NOW)
        again = fsrs.schedule(first, 3, NOW)
        expected = first["stability"] * __import__("math").exp(
            fsrs.DEFAULT_W[17] * (3 - 3 + fsrs.DEFAULT_W[18]))
        self.assertAlmostEqual(again["stability"], expected, places=4)
        self.assertEqual(again["elapsed_days"], 0)

    def test_invalid_rating_rejected(self):
        with self.assertRaises(ValueError):
            fsrs.schedule(None, 0, NOW)
        with self.assertRaises(ValueError):
            fsrs.schedule(None, 5, NOW)

    def test_interval_is_clamped(self):
        huge = {"state": "review", "stability": 100000, "difficulty": 5,
                "reps": 10, "lapses": 0, "last_review": "2020-01-01 09:00:00",
                "due": "2020-01-02"}
        state = fsrs.schedule(huge, 4, NOW)
        self.assertLessEqual(state["scheduled_days"], fsrs.MAX_INTERVAL)
        self.assertGreaterEqual(state["scheduled_days"], 1)


if __name__ == "__main__":
    unittest.main()
