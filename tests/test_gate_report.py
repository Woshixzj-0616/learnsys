"""闸门观测：首 token 落库 + gate_report 口径。"""
from __future__ import annotations

import datetime as dt
import json
import unittest

from learnsys import store
from tools import gate_report


class TestFirstMs(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_add_ask_records_first_ms(self):
        ask_id = store.add_ask(self.conn, "问", "答", 3200, "m", first_ms=850)
        row = self.conn.execute(
            "SELECT ms, first_ms FROM asks WHERE id = ?", (ask_id,)).fetchone()
        self.assertEqual(row[0], 3200)
        self.assertEqual(row[1], 850)

    def test_add_ask_first_ms_optional(self):
        ask_id = store.add_ask(self.conn, "问", "答", 100, "m")
        row = self.conn.execute(
            "SELECT first_ms FROM asks WHERE id = ?", (ask_id,)).fetchone()
        self.assertIsNone(row[0])


class TestGateCollect(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.today = dt.date.today()
        self.start = self.today - dt.timedelta(days=1)
        self.stamp = store.now()

        self.cet6 = store.create_conversation(self.conn, "六级", module="cet6")
        self.ask_conv = store.create_conversation(self.conn, "普通", module="ask")
        store.add_ask(self.conn, "这句什么意思", "答", 4000, "m",
                      conversation_id=self.cet6, first_ms=900)
        store.add_ask(self.conn, "再问一句", "答", 6000, "m",
                      conversation_id=self.cet6, first_ms=1500)
        store.add_ask(self.conn, "普通问题", "答", 9000, "m",
                      conversation_id=self.ask_conv, first_ms=3000)

        self.conn.execute(
            "INSERT INTO service_runs (ts, surface, kind, status, ms, cache_hit, meta_json) "
            "VALUES (?, 'cet6', 'translate', 'done', 120, 0, ?)",
            (self.stamp, json.dumps({"type": "word"})))
        self.conn.execute(
            "INSERT INTO service_runs (ts, surface, kind, status, ms, cache_hit, meta_json) "
            "VALUES (?, 'cet6', 'cet6_analyze', 'done', 300, 1, '{}')",
            (self.stamp,))
        self.conn.execute(
            "INSERT INTO service_results (kind, target_id, status, created_at, updated_at) "
            "VALUES ('cet6_analyze', 'p1', 'done', ?, ?)", (self.stamp, self.stamp))
        self.conn.execute(
            "INSERT INTO service_results (kind, target_id, status, created_at, updated_at) "
            "VALUES ('cet6_analyze', 'p2', 'error', ?, ?)", (self.stamp, self.stamp))
        self.conn.commit()

    def test_collect_counts_only_cet6_asks(self):
        data = gate_report.collect(self.conn, self.start, 3)
        self.assertEqual(data["asks"], 2)
        self.assertEqual(data["translate_actions"], 1)
        self.assertEqual(data["service_runs"], 2)
        self.assertEqual(data["cache_hits"], 1)

    def test_collect_latency_ignores_other_modules(self):
        data = gate_report.collect(self.conn, self.start, 3)
        self.assertEqual(data["first_ms_p95"], 1500)   # 3000 是普通问答，不进来
        self.assertEqual(data["total_ms_p95"], 6000)

    def test_collect_analysis_status(self):
        data = gate_report.collect(self.conn, self.start, 3)
        self.assertEqual(data["analysis_status"].get("done"), 1)
        self.assertEqual(data["analysis_status"].get("error"), 1)

    def test_report_marks_missing_gate(self):
        text = gate_report.format_report(gate_report.collect(self.conn, self.start, 3))
        self.assertIn("未达标", text)
        self.assertIn("窗口未结束", text)


class TestPercentile(unittest.TestCase):
    def test_p95_recent_rank(self):
        self.assertEqual(gate_report._pct([], 95), None)
        self.assertEqual(gate_report._pct([100], 95), 100)
        self.assertEqual(gate_report._pct([100, 200, 300, 400], 95), 400)
        self.assertEqual(gate_report._pct([100, 200, 300, 400], 50), 300)


if __name__ == "__main__":
    unittest.main()
