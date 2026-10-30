# -*- coding: utf-8 -*-
"""能力体检脚本：五个断面能跑、空库不炸、域覆盖看工具清单。"""
from __future__ import annotations

import pathlib
import tempfile
import types
import unittest
from unittest import mock

from learnsys import store
from tools import agent_capability_report as report


def fake_cfg():
    return types.SimpleNamespace(
        vision_ready=False, vision_model="", auto_route="shadow",
        strong_model="strong", price_input=0, price_output=0,
        price_cache_read=0, currency="CNY", data_root=pathlib.Path("."))


class CapabilityReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        store.connect(self.db).close()
        patcher = mock.patch("learnsys.agent.deep.available", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_collect_empty_db(self):
        data = report.collect(self.db, cfg=fake_cfg())
        self.assertEqual(data["perception"]["materials"], 0)
        self.assertEqual(data["perception"]["recordings"], 0)
        self.assertFalse(data["perception"]["vision_ready"])
        self.assertEqual(data["memory"]["memories_active"], 0)
        self.assertEqual(data["tools"]["total"], 31)
        self.assertEqual(data["perception"]["web_tools"], ["fetch_url", "web_search"])
        self.assertEqual(data["tools"]["surface_quickbar"], 18)
        self.assertEqual(data["tools"]["mcp_tools"], 5)
        self.assertTrue(all(data["tools"]["domains"].values()))

    def test_render_has_sections(self):
        text = report.render(report.collect(self.db, cfg=fake_cfg()))
        for section in ("感知面", "工具面", "记忆面", "可靠性", "主动性与互操作"):
            self.assertIn(section, text)
        self.assertIn("8 个数据域都有读工具", text)
        self.assertIn("视觉未启用", text)
        self.assertIn("联网工具：fetch_url、web_search", text)

    def test_missing_db_does_not_raise(self):
        data = report.collect(pathlib.Path(self.tmp.name) / "nope.db",
                              cfg=fake_cfg())
        self.assertEqual(data["memory"]["asks"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
