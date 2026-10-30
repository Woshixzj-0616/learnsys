# -*- coding: utf-8 -*-
"""P30.1 Agent 读工具：生活卡片只给工作台问答，且只读。"""
from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.agent import tools
from learnsys.agent.tools.context import ToolContext


def _names(**kwargs):
    return {schema["name"] for schema in tools.schemas_for(**kwargs)}


class LifeToolSchemaTest(unittest.TestCase):
    def test_only_workbench_ask_surface_gets_life_cards(self):
        self.assertIn("life_cards", _names(mode="explain", surface="ask"))
        self.assertNotIn("life_cards", _names(mode="explain", surface="quickbar"))
        self.assertNotIn("life_cards", _names(mode="explain", surface="cet6"))
        self.assertNotIn("life_cards", _names(mode="explain", surface="video"))
        self.assertNotIn("life_cards", _names(mode="quiz", surface="ask"))
        self.assertNotIn("life_cards", _names(mode="quick", surface="ask"))

    def test_tool_is_read_only(self):
        self.assertNotIn("life_cards", tools.CONFIRM_TOOLS)
        self.assertEqual(tools.LIFE_CARDS_SCHEMA["name"], "life_cards")
        self.assertEqual(
            tools.LIFE_CARDS_SCHEMA["input_schema"].get("required", []), [])


class LifeToolExecuteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db)
        day = dt.date.today().isoformat()
        store.upsert_card(conn, day=day, domain="life", title="AI 前沿",
                          content={"summary": "今天有三条新进展", "kind": "news",
                                   "items": [{"title": "一"}, {"title": "二"}]})
        conn.close()
        self.ctx = ToolContext(data_root=pathlib.Path(self.tmp.name),
                               db_path=self.db)

    def test_reads_today_cards(self):
        text, summary, ok = tools.execute("life_cards", {"days": 1}, self.ctx)
        self.assertTrue(ok)
        self.assertIn("AI 前沿", text)
        self.assertIn("2 条", text)
        self.assertEqual(summary, "读了生活卡片")

    def test_empty_database_is_honest(self):
        empty = pathlib.Path(self.tmp.name) / "empty.db"
        store.connect(empty).close()
        ctx = ToolContext(data_root=pathlib.Path(self.tmp.name), db_path=empty)
        text, _summary, ok = tools.execute("life_cards", {}, ctx)
        self.assertTrue(ok)
        self.assertIn("没有生活卡片", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
