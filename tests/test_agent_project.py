# -*- coding: utf-8 -*-
"""P29.3 派活带交接包：schema 14、project_id、组合顺序与原文保留。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import config as app_config
from learnsys import store
from learnsys.core.db import schema as schema_mod
from learnsys.services.agents import queue


class AgentProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.data_root = root / "data"
        patches = [
            mock.patch.object(app_config, "DATA_ROOT", self.data_root),
            mock.patch.object(app_config, "USER", {}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_schema_is_14_and_has_project_id(self):
        self.assertEqual(schema_mod.SCHEMA_VERSION, 14)
        cols = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(agent_tasks)").fetchall()}
        self.assertIn("project_id", cols)

    def test_task_keeps_project_id_and_original_prompt(self):
        task_id = store.add_agent_task(
            self.conn, agent="claude", prompt="只读看看结构", project_id=7)
        task = store.get_agent_task(self.conn, task_id)
        self.assertEqual(task["project_id"], 7)
        self.assertEqual(task["prompt"], "只读看看结构")

    def test_handoff_block_reads_file(self):
        project = store.upsert_project(
            self.conn, name="甲项目", repo_path=r"D:\示例")
        target = self.data_root / "projects" / "甲项目" / "HANDOFF.md"
        target.parent.mkdir(parents=True)
        target.write_text("# HANDOFF · 甲项目\n下一步：补 P29.3\n", encoding="utf-8")
        store.update_project(self.conn, project["id"], handoff_path=str(target))
        block = queue._project_handoff(self.conn, project["id"])
        self.assertIn("下一步：补 P29.3", block)

    def test_handoff_block_generates_when_missing(self):
        project = store.upsert_project(
            self.conn, name="乙项目", repo_path=r"D:\不存在", next_step="写测试")
        block = queue._project_handoff(self.conn, project["id"])
        self.assertIn("下一步：写测试", block)
        saved = store.get_project(self.conn, project["id"])
        self.assertTrue(pathlib.Path(saved["handoff_path"]).is_file())

    def test_compose_puts_handoff_before_task_and_after_parent(self):
        text = queue.compose_chain_prompt(
            "本轮任务原话", 3, "上一步结果", project_block="交接包内容")
        self.assertLess(text.index("上一步结果"), text.index("交接包内容"))
        self.assertLess(text.index("交接包内容"), text.index("本轮任务原话"))
        self.assertIn("【项目交接包", text)

    def test_compose_without_handoff_keeps_old_shape(self):
        text = queue.compose_chain_prompt("本轮任务原话", 0, "")
        self.assertEqual(text, "本轮任务原话")

    def test_compose_truncates_handoff_before_user_prompt(self):
        user = "任务" * 5000
        text = queue.compose_chain_prompt(user, 0, "",
                                          project_block="交接" * 5000)
        self.assertLessEqual(len(text), queue.MAX_RUN_PROMPT)
        self.assertTrue(text.endswith(user))
        self.assertIn("交接包已截断", text)


if __name__ == "__main__":
    unittest.main()
