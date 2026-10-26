# -*- coding: utf-8 -*-
"""P0 学习域工具：到期复习、掌握度、训练概况、录像列表 + 按入口裁剪。"""
from __future__ import annotations

import datetime
import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.agent import tools


class LearningToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db_path = self.root / "learning.db"
        self.ctx = tools.ToolContext(data_root=self.root, db_path=self.db_path)
        conn = store.connect(self.db_path)
        self.addCleanup(conn.close)
        self.conn = conn

    def test_schemas_registered(self):
        names = [schema["name"] for schema in tools.TOOL_SCHEMAS]
        for name in ("due_reviews", "get_mastery", "get_train_summary",
                     "list_recordings"):
            self.assertIn(name, names)

    def test_due_reviews_empty(self):
        text = tools.due_reviews(ctx=self.ctx)
        self.assertIn("今天没有到期的复习", text)

    def test_due_reviews_reads_wrong_item(self):
        item_id, _ = store.add_wrong_item(
            self.conn, question="1 + 1 = ?", answer="2", my_answer="3",
            tags="算术", source="manual", source_id="manual:t1")
        store.save_review_state(
            self.conn, "wrong", item_id, state="review",
            due=datetime.date.today().isoformat(), reps=2)
        text = tools.due_reviews(ctx=self.ctx)
        self.assertIn(f"错题 #{item_id}", text)
        self.assertIn("1 + 1 = ?", text)
        self.assertIn("复习 2 次", text)

    def test_mastery_reports_not_enough_samples(self):
        text = tools.get_mastery(ctx=self.ctx)
        self.assertIn("知识点", text)
        self.assertTrue("样本" in text or "还没有知识点记录" in text)

    def test_train_summary_empty(self):
        text = tools.get_train_summary(ctx=self.ctx)
        self.assertIn("六级写作/翻译训练", text)
        self.assertIn("还没有已批改", text)

    def test_list_recordings_empty(self):
        self.assertIn("还没有录像", tools.list_recordings(ctx=self.ctx))

    def test_list_recordings_reads_session(self):
        self.conn.execute(
            "INSERT INTO sessions (started_at, title, video_path, video_bytes, duration_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2026-10-26 09:00:00", "线性代数第 3 讲", "C:/nope/video.mp4", 1024, 42000))
        self.conn.commit()
        text = tools.list_recordings(ctx=self.ctx)
        self.assertIn("线性代数第 3 讲", text)
        self.assertIn("42 秒", text)

    def test_execute_routes_new_tools(self):
        for name, preview in (("due_reviews", "查了到期复习"),
                              ("get_mastery", "查了知识点掌握度"),
                              ("get_train_summary", "看了写作翻译训练概况"),
                              ("list_recordings", "查了录像列表")):
            text, got_preview, ok = tools.execute(name, {}, self.ctx)
            self.assertTrue(text, name)
            self.assertEqual(got_preview, preview, name)
            self.assertTrue(ok, name)


class ToolPruningTest(unittest.TestCase):
    def names(self, mode="explain", surface="ask"):
        return {schema["name"] for schema in tools.schemas_for(
            mode, surface=surface)}

    def test_quick_only_memory(self):
        self.assertEqual(self.names("quick"),
                         {"save_memory", "forget_memory"})

    def test_quickbar_has_no_system_or_run_code(self):
        names = self.names(surface="quickbar")
        self.assertIn("get_mastery", names)
        for name in ("run_code", "open_file", "launch_app", "write_study_file"):
            self.assertNotIn(name, names)

    def test_cet6_has_learning_reads_only(self):
        names = self.names(surface="cet6")
        for name in ("due_reviews", "get_mastery", "get_train_summary",
                     "list_recordings", "save_material_note"):
            self.assertIn(name, names)
        for name in ("run_code", "open_file", "save_wrongbook"):
            self.assertNotIn(name, names)

    def test_ask_has_full_tools(self):
        names = self.names("explain", "ask")
        for name in ("run_code", "open_file", "write_study_file",
                     "due_reviews", "get_mastery"):
            self.assertIn(name, names)

    def test_quiz_keeps_wrongbook_but_not_system(self):
        names = self.names("quiz", "ask")
        self.assertIn("save_wrongbook", names)
        self.assertNotIn("open_file", names)

    def test_use_tools_false_returns_none(self):
        self.assertIsNone(tools.schemas_for("explain", use_tools=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
