# -*- coding: utf-8 -*-
"""「调用路径」只读视图：摘要 / 详情 / 缺库 / 坏 flow。"""
import json
import os
import sqlite3
import tempfile
import unittest

from learnsys.store import agent_trace


class AgentTraceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "travel.db")
        con = sqlite3.connect(self.db)
        con.execute("create table trace_log (trace_id text primary key, at text, method text,"
                    " path text, status integer, ms integer, username text, flow text)")
        flow = {"evs": [
            {"e": "gates", "at": 10, "need_search": True},
            {"e": "ask", "at": 12, "q": "北京三日游要多少钱？"},
            {"e": "llm", "at": 20, "n": 1, "ms": 800, "tin": 100, "tout": 20},
            {"e": "tool", "at": 25, "name": "web_search", "kind": "tool", "ok": True, "ms": 30},
            {"e": "spans", "at": 99, "total_ms": 900, "llm_ms": 800, "tools_ms": 30},
            {"e": "end", "at": 100, "ended": "ok", "rounds": 2, "calls": 1, "chars": 88},
        ]}
        con.execute("insert into trace_log values (?,?,?,?,?,?,?,?)",
                    ("t1", "2026-11-16 10:00:00", "POST", "/api/chat", 200, 900,
                     "u1", json.dumps(flow, ensure_ascii=False)))
        con.execute("insert into trace_log values (?,?,?,?,?,?,?,?)",
                    ("t2", "2026-11-16 10:01:00", "POST", "/api/other", 200, 10,
                     "u1", "{}"))
        con.execute("insert into trace_log values (?,?,?,?,?,?,?,?)",
                    ("t3", "2026-11-16 10:02:00", "POST", "/api/chat", 200, 20,
                     "u2", json.dumps({"evs": [{"e": "ask", "q": "另一个人的问题"}]},
                                      ensure_ascii=False)))
        con.commit()
        con.close()
        self._orig = agent_trace.db_path
        agent_trace.db_path = lambda: self.db

    def tearDown(self):
        agent_trace.db_path = self._orig
        self.tmp.cleanup()

    def test_list_only_chat_and_summary(self):
        data = agent_trace.list_recent(10)
        self.assertTrue(data["ok"])
        self.assertEqual([x["trace_id"] for x in data["items"]], ["t3", "t1"])
        summary = data["items"][1]["summary"]
        self.assertEqual(summary["question"], "北京三日游要多少钱？")
        self.assertEqual(summary["llm_calls"], 1)
        self.assertEqual(summary["tool_calls"], 1)
        self.assertEqual(summary["calls"], 1)
        self.assertEqual(summary["chars"], 88)
        self.assertEqual(summary["total_ms"], 900)

    def test_list_filters_username(self):
        data = agent_trace.list_recent(10, username="u2")
        self.assertTrue(data["ok"])
        self.assertEqual([x["trace_id"] for x in data["items"]], ["t3"])
        self.assertEqual(data["items"][0]["summary"]["question"], "另一个人的问题")

    def test_get_returns_events(self):
        data = agent_trace.get("t1")
        self.assertIsNotNone(data)
        self.assertEqual(data["trace_id"], "t1")
        self.assertEqual(len(data["events"]), 6)
        self.assertEqual(data["summary"]["ended"], "ok")
        self.assertIsNone(agent_trace.get("nope"))

    def test_missing_db_is_empty_not_crash(self):
        agent_trace.db_path = lambda: os.path.join(self.tmp.name, "missing.db")
        data = agent_trace.list_recent(10)
        self.assertFalse(data["ok"])
        self.assertEqual(data["items"], [])
        self.assertIsNone(agent_trace.get("t1"))

    def test_bad_flow_does_not_crash(self):
        con = sqlite3.connect(self.db)
        con.execute("update trace_log set flow='not json' where trace_id='t1'")
        con.commit()
        con.close()
        data = agent_trace.get("t1")
        self.assertIsNotNone(data)
        self.assertEqual(data["events"], [])


if __name__ == "__main__":
    unittest.main()
