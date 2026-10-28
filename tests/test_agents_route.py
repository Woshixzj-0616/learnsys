# -*- coding: utf-8 -*-
"""P26.3 外部 agent 影子路由：纯规则建议 + route_json 落库。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.services.agents import route

AVAILABLE = {"claude": True, "codex": True}
NAMES = {"claude": "Claude Code", "codex": "Codex CLI"}


def rows(done: int, failed: int = 0, cancelled: int = 0,
         duration_ms: int = 10000, cost_usd: float = 0.0) -> list[dict]:
    data = [{"status": "done", "duration_ms": duration_ms, "cost_usd": cost_usd}
            for _ in range(done)]
    data += [{"status": "failed", "duration_ms": 0, "cost_usd": 0.0}
             for _ in range(failed)]
    data += [{"status": "cancelled", "duration_ms": 0, "cost_usd": 0.0}
             for _ in range(cancelled)]
    return data


class RecommendTest(unittest.TestCase):
    def _run(self, *, mode="read", chosen="claude", history=None, available=None):
        return route.recommend(
            mode=mode, chosen=chosen, available=available or AVAILABLE,
            history=history or {}, names=NAMES)

    def test_insufficient_samples_keeps_choice(self):
        data = self._run(history={"claude": rows(1), "codex": rows(5)})
        self.assertEqual(data["recommended"], "claude")
        self.assertEqual(data["fallback"], "insufficient_samples")
        self.assertIn("样本不足", data["reason"])

    def test_other_agent_unavailable(self):
        data = self._run(available={"claude": True, "codex": False})
        self.assertEqual(data["recommended"], "claude")
        self.assertEqual(data["fallback"], "other_unavailable")
        self.assertIn("不可用", data["reason"])

    def test_write_prefers_claude(self):
        data = self._run(mode="write", chosen="codex", history={
            "claude": rows(5), "codex": rows(5, duration_ms=1000)})
        self.assertEqual(data["recommended"], "claude")
        self.assertIn("逐条", data["reason"])
        self.assertEqual(data["chosen"], "codex")

    def test_completion_rate_gap_wins(self):
        data = self._run(history={
            "claude": rows(2, failed=6, duration_ms=1000),
            "codex": rows(9, failed=1, duration_ms=90000)})
        self.assertEqual(data["recommended"], "codex")
        self.assertIn("完成率", data["reason"])

    def test_cancelled_excluded_from_rate(self):
        data = self._run(history={
            "claude": rows(4, failed=1, cancelled=20, duration_ms=1000),
            "codex": rows(4, failed=1, duration_ms=60000)})
        self.assertNotEqual(data["fallback"], "insufficient_samples")
        self.assertEqual(data["samples"]["claude"]["n"], 5)
        self.assertEqual(data["samples"]["claude"]["cancelled"], 20)

    def test_faster_agent_wins_when_rates_close(self):
        data = self._run(history={
            "claude": rows(5, duration_ms=50000),
            "codex": rows(5, duration_ms=10000)})
        self.assertEqual(data["recommended"], "codex")
        self.assertIn("中位耗时", data["reason"])

    def test_cost_only_compared_when_both_have_numbers(self):
        data = self._run(history={
            "claude": rows(5, duration_ms=10000, cost_usd=0.05),
            "codex": rows(5, duration_ms=10000, cost_usd=0.01)})
        self.assertEqual(data["recommended"], "codex")
        self.assertIn("费用", data["reason"])

        no_cost = self._run(history={
            "claude": rows(5, duration_ms=10000, cost_usd=0.05),
            "codex": rows(5, duration_ms=10000, cost_usd=0.0)})
        self.assertEqual(no_cost["recommended"], "claude")
        self.assertIn("费用无可比数据", no_cost["reason"])

    def test_no_gap_keeps_choice(self):
        data = self._run(history={
            "claude": rows(5, duration_ms=10000),
            "codex": rows(5, duration_ms=10000)})
        self.assertEqual(data["recommended"], "claude")
        self.assertEqual(data["fallback"], "")


class RouteJsonStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(pathlib.Path(self.tmp.name) / "learning.db")
        self.addCleanup(self.conn.close)

    def test_route_json_round_trip(self):
        payload = '{"v": 1, "recommended": "codex", "chosen": "claude"}'
        task_id = store.add_agent_task(
            self.conn, agent="claude", prompt="读", route_json=payload)
        task = store.get_agent_task(self.conn, task_id)
        self.assertEqual(task["route"]["recommended"], "codex")
        self.assertEqual(task["agent"], "claude")     # 影子建议不改实际 agent

    def test_broken_route_json_is_safe(self):
        task_id = store.add_agent_task(
            self.conn, agent="claude", prompt="读", route_json="不是 JSON")
        task = store.get_agent_task(self.conn, task_id)
        self.assertEqual(task["route"], {})


if __name__ == "__main__":
    unittest.main()
