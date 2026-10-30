# -*- coding: utf-8 -*-
"""P30.1 订阅调度：到期生成、失败退避、未就绪不记时间。"""
from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.services.life import cards, scheduler

NOW = dt.datetime(2026, 10, 30, 8, 0, 0)


class LifeSchedulerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        self.orig_connect = store.connect
        self.conn = self.orig_connect(self.db)
        self.addCleanup(self.conn.close)
        patcher = mock.patch.object(
            scheduler.store, "connect",
            side_effect=lambda: self.orig_connect(self.db))
        patcher.start()
        self.addCleanup(patcher.stop)
        scheduler._FAILED_UNTIL.clear()
        self.addCleanup(scheduler._FAILED_UNTIL.clear)

    def _sub(self, **overrides):
        data = {"topic": "AI", "kind": "custom", "cadence": "daily",
                "at_time": "07:30", "enabled": True}
        data.update(overrides)
        return store.upsert_subscription(self.conn, **data)

    def test_due_subscription_generates_and_marks_run(self):
        sub = self._sub()
        with mock.patch.object(cards, "generate",
                               return_value={"id": 1}) as generate:
            scheduler.tick(NOW)
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[1]["id"], sub["id"])
        self.assertTrue(store.get_subscription(self.conn, sub["id"])["last_run"])

    def test_disabled_subscription_is_skipped(self):
        self._sub(enabled=False)
        with mock.patch.object(cards, "generate") as generate:
            scheduler.tick(NOW)
        generate.assert_not_called()

    def test_future_time_is_skipped(self):
        self._sub(at_time="09:30")
        with mock.patch.object(cards, "generate") as generate:
            scheduler.tick(NOW)
        generate.assert_not_called()

    def test_not_ready_retries_next_tick_without_backoff(self):
        sub = self._sub()
        with mock.patch.object(cards, "generate",
                               side_effect=cards.LifeNotReady("简报还没生成")) as generate:
            scheduler.tick(NOW)
            scheduler.tick(NOW + dt.timedelta(minutes=5))
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(store.get_subscription(self.conn, sub["id"])["last_run"], "")

    def test_failure_backs_off_for_thirty_minutes(self):
        sub = self._sub()
        with mock.patch.object(cards, "generate",
                               side_effect=RuntimeError("模型挂了")) as generate:
            scheduler.tick(NOW)
            scheduler.tick(NOW + dt.timedelta(minutes=5))
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(store.get_subscription(self.conn, sub["id"])["last_run"], "")
        with mock.patch.object(cards, "generate", return_value={"id": 1}) as retry:
            scheduler.tick(NOW + dt.timedelta(minutes=31))
        self.assertEqual(retry.call_count, 1)
        self.assertTrue(store.get_subscription(self.conn, sub["id"])["last_run"])

    def test_unsupported_kind_is_marked_run_once(self):
        sub = self._sub(topic="黄金价格", kind="price")
        with mock.patch.object(cards, "generate",
                               side_effect=cards.LifeUnsupported("暂不支持")):
            scheduler.tick(NOW)
        self.assertTrue(store.get_subscription(self.conn, sub["id"])["last_run"])

    def test_one_failure_does_not_block_others(self):
        bad = self._sub(topic="坏的", kind="custom")
        good = self._sub(topic="好的", kind="custom")
        def fake(conn, sub, day):
            if sub["id"] == bad["id"]:
                raise RuntimeError("坏了")
            return {"id": 2}
        with mock.patch.object(cards, "generate", side_effect=fake):
            scheduler.tick(NOW)
        self.assertTrue(store.get_subscription(self.conn, good["id"])["last_run"])
        self.assertEqual(store.get_subscription(self.conn, bad["id"])["last_run"], "")

    def test_ensure_started_skips_in_test_process(self):
        scheduler.ensure_started()
        self.assertIsNone(scheduler._THREAD)


if __name__ == "__main__":
    unittest.main(verbosity=2)
