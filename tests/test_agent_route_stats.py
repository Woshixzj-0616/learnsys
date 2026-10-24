# -*- coding: utf-8 -*-
"""影子路由汇总：只读 agent_runs.trace，不新增表。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import store


def route(tier: str, model: str, auto: str = "shadow", recommended: dict | None = None,
          reason: str = "速度档：平衡") -> list[dict]:
    data = {"tier": tier, "model": model, "thinking": False, "reason": reason,
            "auto": auto}
    if recommended:
        data["recommended"] = recommended
    return [{"kind": "route", "data": data}]


class RouteStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.conn = store.connect(self.root / "learning.db")
        self.addCleanup(self.conn.close)

    def _add(self, run_id: str, trace: list[dict], started_at: str = "") -> None:
        store.add_agent_run(self.conn, run_id=run_id, question=f"问题 {run_id}",
                            started_at=started_at or store.now(), trace=trace)

    def test_shadow_and_on_counts(self):
        self._add("a", route("standard", "flash", "shadow", {
            "tier": "deep", "model": "pro", "thinking": True,
            "reason": "复杂度 3：5 个难度词"}))
        self._add("b", route("standard", "flash", "shadow", {
            "tier": "standard", "model": "flash", "thinking": False,
            "reason": "复杂度 0：没有明显难度信号"}))
        self._add("c", [])                                    # 没开路由
        self._add("d", route("deep", "pro", "on"))            # on：实际就是 deep

        stats = store.route_stats(self.conn, days=0)
        self.assertEqual(stats["runs"], 4)
        self.assertEqual(stats["with_route"], 3)
        self.assertEqual(stats["escalations"], 2)
        self.assertAlmostEqual(stats["escalation_rate"], 0.667, places=3)
        self.assertEqual(stats["actual_tiers"], {"standard": 2, "deep": 1})
        self.assertEqual(stats["recommended_tiers"], {"deep": 2, "standard": 1})
        self.assertEqual(stats["auto_modes"], {"shadow": 2, "on": 1})
        reason_counts = {item["reason"]: item["count"] for item in stats["reasons"]}
        self.assertEqual(reason_counts["复杂度 3"], 1)
        self.assertEqual(reason_counts["速度档"], 1)
        self.assertEqual(len(stats["samples"]), 2)

    def test_days_filter_and_malformed_trace(self):
        self._add("old", route("standard", "flash"), started_at="2020-01-01 10:00:00")
        self._add("new", route("standard", "flash"))
        self.conn.execute("UPDATE agent_runs SET trace_json = '不是 JSON' "
                          "WHERE run_id = 'new'")
        self.conn.commit()

        recent = store.route_stats(self.conn, days=7)
        self.assertEqual(recent["runs"], 1)
        self.assertEqual(recent["with_route"], 0)             # 坏 trace 不算，也不炸

        everything = store.route_stats(self.conn, days=0)
        self.assertEqual(everything["runs"], 2)
        self.assertEqual(everything["with_route"], 1)

    def test_daily_breakdown(self):
        self._add("a", route("standard", "flash", "shadow", {
            "tier": "deep", "model": "pro", "thinking": True, "reason": "复杂度 3：x"}))
        self._add("b", [])
        stats = store.route_stats(self.conn, days=0)
        self.assertEqual(len(stats["daily"]), 1)
        day = stats["daily"][0]
        self.assertEqual(day["runs"], 2)
        self.assertEqual(day["routes"], 1)
        self.assertEqual(day["escalations"], 1)


if __name__ == "__main__":
    unittest.main()
