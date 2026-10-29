# -*- coding: utf-8 -*-
"""快捷栏个人状态：60 秒缓存、失败不缓存、AgentRequest 带上字符串。"""
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from learnsys.ask.quickbar import workers


class QuickbarPersonalStateTest(unittest.TestCase):
    def setUp(self):
        workers.reset_personal_state_cache()
        self.addCleanup(workers.reset_personal_state_cache)

    def test_cache_lasts_60_seconds(self):
        with mock.patch.object(workers, "_load_personal_state",
                               return_value="学习：今日 1/3") as load:
            self.assertEqual(workers.personal_state(now=1000.0), "学习：今日 1/3")
            self.assertEqual(workers.personal_state(now=1030.0), "学习：今日 1/3")
            self.assertEqual(load.call_count, 1, "60 秒内不应重复查库")
            self.assertEqual(workers.personal_state(now=1061.0), "学习：今日 1/3")
            self.assertEqual(load.call_count, 2, "超过 60 秒要重新查")

    def test_failure_returns_empty_and_is_not_cached(self):
        with mock.patch.object(workers, "_load_personal_state",
                               side_effect=RuntimeError("库忙")) as load:
            self.assertEqual(workers.personal_state(now=1000.0), "")
            self.assertEqual(workers.personal_state(now=1001.0), "")
            self.assertEqual(load.call_count, 2, "失败不能缓存 60 秒")

    def test_empty_state_is_cached(self):
        with mock.patch.object(workers, "_load_personal_state",
                               return_value="") as load:
            self.assertEqual(workers.personal_state(now=2000.0), "")
            self.assertEqual(workers.personal_state(now=2010.0), "")
            self.assertEqual(load.call_count, 1)

    def test_worker_request_carries_personal_state(self):
        source = pathlib.Path(workers.__file__).read_text(encoding="utf-8")
        self.assertIn("personal_state=personal_state()", source)


if __name__ == "__main__":
    unittest.main()
