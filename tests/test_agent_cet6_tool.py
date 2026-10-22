# -*- coding: utf-8 -*-
"""Agent 工具 get_cet6_context：schema、无记录、有记录、显隐格式。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.agent import tools


class GetCet6ContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        self.ctx = tools.ToolContext(data_root=pathlib.Path(self.tmp.name),
                                     db_path=self.db_path)
        conn = store.connect(self.db_path)
        self.addCleanup(conn.close)
        self.conn = conn

    def test_schema_registered(self):
        names = [schema["name"] for schema in tools.TOOL_SCHEMAS]
        self.assertIn("get_cet6_context", names)

    def test_no_records(self):
        text = tools.get_cet6_context(ctx=self.ctx)
        self.assertIn("还没有六级精听记录", text)

    def test_reads_latest_item(self):
        store.upsert_cet6_progress(
            self.conn, paper_id="p1", paper_title="测试卷", section="Section A",
            item="C1", rows=[
                {"sentence": 1, "en": "Hello.", "tags": ["生词"], "note": "没听清",
                 "loops": 3, "plays": 4},
                {"sentence": 2, "en": "World.", "tags": []},
            ], done=[1])
        text = tools.get_cet6_context(ctx=self.ctx)
        self.assertIn("测试卷", text)
        self.assertIn("第 1 句", text)
        self.assertIn("已完成", text)
        self.assertIn("生词", text)
        self.assertIn("循环回绕 3 次", text)
        self.assertIn("Hello.", text)

    def test_execute_routes_to_tool(self):
        text, preview, ok = tools.execute(
            "get_cet6_context", {}, self.ctx)
        self.assertIn("六级", text)
        self.assertEqual(preview, "读了六级精听进度")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
