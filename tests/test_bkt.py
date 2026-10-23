# -*- coding: utf-8 -*-
"""BKT 纯函数：公式、顺序、边界、参数与等级。"""
from __future__ import annotations

import unittest

from learnsys.services import bkt


class BktMathTest(unittest.TestCase):
    def test_empty_is_prior(self):
        self.assertAlmostEqual(bkt.mastery([]), bkt.PARAMS["p_l0"], places=6)

    def test_single_observations(self):
        self.assertAlmostEqual(bkt.observe(0.1, True), 0.392857, places=5)
        self.assertAlmostEqual(bkt.observe(0.1, False), 0.162409, places=5)

    def test_five_correct_and_five_wrong(self):
        high = bkt.mastery([True] * 5)
        low = bkt.mastery([False] * 5)
        self.assertGreater(high, 0.99)
        self.assertLess(low, 0.2)
        self.assertGreater(high, low)

    def test_order_matters(self):
        a = bkt.mastery([True, False])
        b = bkt.mastery([False, True])
        self.assertAlmostEqual(a, 0.217511, places=5)
        self.assertAlmostEqual(b, 0.499418, places=5)
        self.assertNotEqual(a, b)

    def test_clamp_and_no_mutation(self):
        values = [True] * 200
        before = list(values)
        self.assertLessEqual(bkt.mastery(values), 0.999)
        self.assertGreaterEqual(bkt.mastery([False] * 200), 0.001)
        self.assertEqual(values, before)

    def test_none_correct_is_rejected(self):
        with self.assertRaises(ValueError):
            bkt.observe(0.5, None)
        with self.assertRaises(ValueError):
            bkt.mastery([True, None])

    def test_level_boundaries(self):
        self.assertEqual(bkt.level(None, 0), "未开始")
        self.assertEqual(bkt.level(None, 4), "样本不足")
        self.assertEqual(bkt.level(0.3999, 5), "薄弱")
        self.assertEqual(bkt.level(0.4, 5), "在学")
        self.assertEqual(bkt.level(0.6999, 5), "在学")
        self.assertEqual(bkt.level(0.7, 5), "掌握")
        self.assertEqual(bkt.level(0.9, 5, modeled=False), "不建模")

    def test_params_meta(self):
        meta = bkt.params_meta()
        self.assertEqual(meta["min_samples"], 5)
        self.assertEqual(meta["weak_below"], 0.4)
        self.assertEqual(meta["mastered_at"], 0.7)
        self.assertEqual(meta["excluded"], ["其他"])
        self.assertEqual(meta["params"], bkt.PARAMS)


if __name__ == "__main__":
    unittest.main()
