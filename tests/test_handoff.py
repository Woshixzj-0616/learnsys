# -*- coding: utf-8 -*-
"""P29.2 HANDOFF：只含指针和状态、只写数据目录、不写回仓库。"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import config as app_config
from learnsys import store
from learnsys.services import handoff


class HandoffBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.data_root = root / "data"
        self.repo = root / "repo"
        self.memory = root / "memory"
        (self.repo / "docs" / "施工单").mkdir(parents=True)
        (self.repo / "README.md").write_text("# 示例项目\n第一段说明。\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("# 约定\n", encoding="utf-8")
        (self.repo / "docs" / "施工单" / "P29-工作交接.md").write_text(
            "# P29\n", encoding="utf-8")
        (self.repo / "docs" / "架构-前后端.md").write_text("# 架构\n", encoding="utf-8")
        folder = self.memory / "项目" / "甲项目"
        folder.mkdir(parents=True)
        (folder / "02-项目现状.md").write_text(
            "# 项目现状\n\n生产 2.45.1，P28 闭环完成，下一步 P29。\n\n第二段不该出现。\n",
            encoding="utf-8")
        (folder / "04-项目坑与经验.md").write_text(
            "# 坑\n\n打包版不能用 sys.executable 跑 Python。\n", encoding="utf-8")

        patches = [
            mock.patch.object(app_config, "DATA_ROOT", self.data_root),
            mock.patch.object(app_config, "USER",
                              {"handoff_memory_root": str(self.memory)}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.project = store.upsert_project(
            self.conn, name="甲项目", repo_path=str(self.repo),
            status="active", next_step="补 P29.2", risk="外部记忆路径可能不存在")

    def test_contains_status_and_pointers(self):
        text = handoff.build(self.conn, self.project)
        self.assertIn("# HANDOFF · 甲项目", text)
        self.assertIn("自动生成，不手改", text)
        self.assertIn("下一步：补 P29.2", text)
        self.assertIn("风险：外部记忆路径可能不存在", text)
        self.assertIn("README.md", text)
        self.assertIn("AGENTS.md", text)
        self.assertIn("docs/施工单/P29-工作交接.md", text)
        self.assertIn("架构-前后端.md", text)

    def test_latest_docs_follow_mtime_not_filename(self):
        old_doc = self.repo / "docs" / "施工单" / "闸门-旧.md"
        old_doc.write_text("# 旧\n", encoding="utf-8")
        os.utime(old_doc, (1, 1))
        new_doc = self.repo / "docs" / "施工单" / "P29-工作交接.md"
        os.utime(new_doc, (2_000_000_000, 2_000_000_000))
        text = handoff.build(self.conn, self.project)
        self.assertLess(text.index("P29-工作交接.md"),
                        text.index("闸门-旧.md"))

    def test_memory_name_mismatch_lists_existing_projects(self):
        project = dict(self.project, name="名字对不上的项目")
        text = handoff.build(self.conn, project)
        self.assertIn("未找到项目记忆档", text)
        self.assertIn("现有项目档", text)
        self.assertIn("甲项目", text)

    def test_contains_memory_first_paragraph_and_full_path(self):
        text = handoff.build(self.conn, self.project)
        self.assertIn("生产 2.45.1，P28 闭环完成，下一步 P29。", text)
        self.assertIn("打包版不能用 sys.executable", text)
        self.assertIn(str(self.memory / "项目" / "甲项目" / "02-项目现状.md"), text)
        # 只给首段，不搬第二段正文
        self.assertNotIn("第二段不该出现", text)

    def test_missing_memory_root_is_not_fatal(self):
        with mock.patch.object(app_config, "USER", {}), \
                mock.patch.object(handoff, "DEFAULT_MEMORY_ROOT",
                                  self.memory / "不存在"):
            text = handoff.build(self.conn, self.project)
        self.assertIn("未配置外部记忆库", text)

    def test_missing_repo_marks_invalid(self):
        project = dict(self.project, repo_path=str(self.repo / "不存在"))
        text = handoff.build(self.conn, project)
        self.assertIn("路径失效", text)

    def test_write_goes_to_data_root_not_repo(self):
        text, path = handoff.write(self.conn, self.project)
        self.assertTrue(path.is_file())
        self.assertEqual(path, self.data_root / "projects" / "甲项目" / "HANDOFF.md")
        self.assertEqual(path.read_text(encoding="utf-8"), text)
        self.assertFalse((self.repo / "HANDOFF.md").exists())
        self.assertFalse(list(self.repo.rglob("HANDOFF.md")))

    def test_write_backfills_handoff_path(self):
        _, path = handoff.write(self.conn, self.project)
        saved = store.get_project(self.conn, self.project["id"])
        self.assertEqual(saved["handoff_path"], str(path))

    def test_name_is_sanitized(self):
        self.assertEqual(handoff.safe_name('a/b:c*?"<>|'), "a_b_c______")
        self.assertEqual(handoff.safe_name("  ..  "), "未命名项目")
        self.assertEqual(handoff.safe_name("学习 工作台"), "学习 工作台")

    def test_length_is_capped(self):
        big = dict(self.project, next_step="很长的下一步" * 2000)
        text = handoff.build(self.conn, big)
        self.assertLessEqual(len(text), handoff.MAX_CHARS + 40)
        self.assertIn("已截断", text)


if __name__ == "__main__":
    unittest.main()
