# -*- coding: utf-8 -*-
"""P30.3 Agent 读工具：创作库只给工作台问答。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.agent import tools
from learnsys.agent.tools.context import ToolContext


def _names(**kwargs):
    return {schema["name"] for schema in tools.schemas_for(**kwargs)}


class ArtToolTest(unittest.TestCase):
    def test_only_workbench_ask_surface_gets_art_works(self):
        self.assertIn("art_works", _names(mode="explain", surface="ask"))
        for kwargs in ({"mode": "explain", "surface": "quickbar"},
                       {"mode": "explain", "surface": "cet6"},
                       {"mode": "explain", "surface": "video"},
                       {"mode": "quiz", "surface": "ask"},
                       {"mode": "quick", "surface": "ask"}):
            self.assertNotIn("art_works", _names(**kwargs))
        self.assertNotIn("art_works", tools.CONFIRM_TOOLS)
        self.assertEqual(tools.ART_WORKS_SCHEMA["name"], "art_works")

    def test_reads_works_and_presets(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = pathlib.Path(tmp) / "learning.db"
            conn = store.connect(db)
            preset = store.upsert_art_preset(conn, name="水彩")
            store.add_art_work(conn, title="山谷", prompt="晨雾中的山谷",
                               preset_id=preset["id"], model="豆包")
            conn.close()
            ctx = ToolContext(data_root=pathlib.Path(tmp), db_path=db)
            text, summary, ok = tools.execute("art_works", {}, ctx)
            self.assertTrue(ok)
            self.assertIn("山谷", text)
            self.assertIn("水彩", text)
            self.assertIn("晨雾中的山谷", text)
            self.assertEqual(summary, "读了创作库")

    def test_empty_database_is_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = pathlib.Path(tmp) / "learning.db"
            store.connect(db).close()
            ctx = ToolContext(data_root=pathlib.Path(tmp), db_path=db)
            text, _summary, ok = tools.execute("art_works", {}, ctx)
            self.assertTrue(ok)
            self.assertIn("没有作品", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
