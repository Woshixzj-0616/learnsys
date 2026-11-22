# -*- coding: utf-8 -*-
"""智能旅行 trace 只读工具：列表 / 最慢 / 详情 / 缺库 / 工具注册。"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from learnsys.agent import tools
from learnsys.agent.tools import travel
from learnsys.store import agent_trace


def _flow(question: str, total_ms: int) -> str:
    return json.dumps({"evs": [
        {"e": "ask", "q": question},
        {"e": "llm", "ms": total_ms - 100, "tin": 100, "tout": 20},
        {"e": "tool", "name": "web_search", "ok": True, "ms": 100},
        {"e": "nudge", "flag": "need_search"},
        {"e": "spans", "total_ms": total_ms,
         "llm_ms": total_ms - 100, "tools_ms": 100},
        {"e": "end", "ended": "ok", "rounds": 2, "calls": 1, "chars": 88},
    ]}, ensure_ascii=False)


class TravelToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "travel.db")
        con = sqlite3.connect(self.db)
        con.execute("create table trace_log (trace_id text primary key, at text,"
                    " method text, path text, status integer, ms integer,"
                    " username text, flow text)")
        con.execute("insert into trace_log values (?,?,?,?,?,?,?,?)",
                    ("t1", "2026-11-16 10:00:00", "POST", "/api/chat", 200,
                     900, "u1", _flow("北京三日游要多少钱？", 900)))
        con.execute("insert into trace_log values (?,?,?,?,?,?,?,?)",
                    ("t2", "2026-11-16 10:01:00", "POST", "/api/chat", 200,
                     4200, "u2", _flow("帮我排一个五日行程", 4200)))
        con.commit()
        con.close()
        self._orig = agent_trace.db_path
        agent_trace.db_path = lambda: self.db

    def tearDown(self):
        agent_trace.db_path = self._orig
        self.tmp.cleanup()

    def test_list_is_readable_and_hides_username(self):
        text = travel.travel_trace_summary(limit=10)
        self.assertIn("北京三日游要多少钱", text)
        self.assertIn("4200 ms", text)
        self.assertIn("1 次打回", text)
        self.assertNotIn("u1", text)
        self.assertNotIn("u2", text)

    def test_slow_only_sorts_desc(self):
        text = travel.travel_trace_summary(limit=10, slow_only=True)
        self.assertLess(text.index("t2"), text.index("t1"))

    def test_trace_detail_has_events(self):
        text = travel.travel_trace_summary(trace_id="t1")
        self.assertIn("llm", text)
        self.assertIn("web_search", text)
        self.assertIn("spans", text)

    def test_missing_db_returns_chinese_reason(self):
        agent_trace.db_path = lambda: os.path.join(self.tmp.name, "missing.db")
        text = travel.travel_trace_summary()
        self.assertTrue(text.startswith("读智能旅行 trace 失败"))

    def test_registered_for_quickbar(self):
        schemas = tools.schemas_for("explain", surface="quickbar")
        names = {schema["name"] for schema in schemas}
        self.assertIn("travel_trace", names)
        self.assertEqual(tools.label_for("travel_trace"), "查智能旅行路径")

    def test_execute_returns_ok(self):
        text, label, ok = tools.execute("travel_trace", {"limit": 5}, None)
        self.assertTrue(ok)
        self.assertEqual(label, "查了智能旅行调用路径")
        self.assertIn("智能旅行", text)


if __name__ == "__main__":
    unittest.main()
