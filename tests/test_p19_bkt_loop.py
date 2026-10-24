# -*- coding: utf-8 -*-
"""P19：BKT 接回学习闭环——今天页薄弱点卡 + 测验优先薄弱类目。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock
from urllib.parse import unquote

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.services import study
from learnsys.server.app import create_app
from learnsys.services import knowledge as service

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


def _point(name, mastery, attempts, *, ready=True, sort=10, pid=1):
    return {"id": pid, "name": name, "mastery": mastery,
            "mastery_attempts": attempts, "mastery_ready": ready,
            "sort": sort}


class WeakPointsPureTest(unittest.TestCase):
    def test_empty_and_no_ready(self):
        self.assertEqual(service.weak_points([]), [])
        points = [_point("阅读", None, 2, ready=False, pid=2),
                  _point("其他", None, 0, ready=False, sort=999, pid=8)]
        self.assertEqual(service.weak_points(points), [])

    def test_sorted_by_mastery_then_samples(self):
        points = [_point("语法", 0.5, 5, sort=30, pid=3),
                  _point("阅读", 0.2, 5, sort=70, pid=7),
                  _point("词汇", 0.2, 8, sort=10, pid=1),
                  _point("语音", 0.8, 5, sort=20, pid=2)]
        names = [p["name"] for p in service.weak_points(points)]
        # 掌握度升序；并列时样本多的优先
        self.assertEqual(names, ["词汇", "阅读", "语法"])

    def test_limit(self):
        points = [_point(f"P{i}", 0.1 * i, 5, pid=i) for i in range(5)]
        self.assertEqual(len(service.weak_points(points, limit=2)), 2)
        self.assertEqual(service.weak_points(points, limit=0), [])

    def test_fields(self):
        row = service.weak_points([_point("阅读", 0.1734, 5, pid=7)])[0]
        self.assertEqual(row["name"], "阅读")
        self.assertEqual(row["attempts"], 5)
        self.assertAlmostEqual(row["mastery"], 0.1734)

    def test_mastered_points_are_not_weak(self):
        points = [_point("词汇", 0.9, 5, sort=10, pid=1),
                  _point("阅读", 0.75, 5, sort=70, pid=7)]
        self.assertEqual(service.weak_points(points), [])


class BuilderPureTest(unittest.TestCase):
    def test_without_weak_keeps_2_15_contract(self):
        text = study.build_quiz_question([], [], "")
        self.assertNotIn("【本轮重点】", text)
        self.assertIn("【知识点】", text)

    def test_with_weak_points_and_focus(self):
        text = study.build_quiz_question(
            [], [], "",
            weak_points=[{"name": "阅读", "mastery": 0.17, "attempts": 5}],
            focus="阅读")
        self.assertIn("【本轮重点】", text)
        self.assertIn("阅读 17%", text)
        self.assertIn("至少 3 道", text)
        self.assertIn("「阅读」", text)

    def test_weak_points_without_focus(self):
        text = study.build_quiz_question(
            [], [], "", weak_points=[{"name": "语法", "mastery": 0.32, "attempts": 5}])
        self.assertIn("语法 32%", text)
        self.assertNotIn("本轮指定重点", text)

    def test_only_weak_without_today_context(self):
        text = study.build_quiz_question(
            [], [], "", weak_points=[{"name": "阅读", "mastery": 0.17, "attempts": 5}])
        self.assertIn("没有新的学习记录", text)
        self.assertIn("通识自测题", text)
        self.assertNotIn("别超纲", text)

    def test_with_context_stays_grounded(self):
        text = study.build_quiz_question(
            ["09:00 起记了 30 分钟"], [], "课堂内容",
            weak_points=[{"name": "阅读", "mastery": 0.17, "attempts": 5}])
        self.assertIn("别超纲", text)
        self.assertNotIn("通识自测题", text)


class TodayAndStudyApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def add_attempt(self, correct, points, n=1):
        return service.add_attempt(
            self.conn, conversation_id=n, question=f"第 {n} 题：{points[0]}",
            my_answer=f"答案 {n}", correct=correct, points=points)

    def add_wrong(self, question="What does the speaker imply?"):
        return store.add_wrong_item(
            self.conn, source="quiz", source_id="quiz:99:abcdef0123456789",
            question=question, answer="正确答案", my_answer="我答错了",
            tags="听力推断", material_id=0)

    def weak_action(self):
        data = self.client.get("/api/today", headers=AUTH).json()
        weak = [a for a in data["actions"] if a["kind"] == "weak"]
        self.assertEqual(len(weak), 1)
        return weak[0]

    def test_falls_back_to_wrong_item_without_ready_samples(self):
        self.add_wrong()
        self.add_attempt(False, ["阅读"], n=1)       # 只有 1 条，样本不足
        action = self.weak_action()
        self.assertIn("最近错的", action["detail"])
        self.assertEqual(action["href"], "#/quiz")

    def test_weak_card_reads_bkt(self):
        for i in range(1, 6):
            self.add_attempt(False, ["阅读"], n=i)
        for i in range(6, 11):
            self.add_attempt(True, ["词汇"], n=i)
        action = self.weak_action()
        self.assertIn("阅读", action["title"])
        self.assertIn("掌握度", action["detail"])
        self.assertEqual(unquote(action["href"]), "#/quiz?focus=阅读")

    def test_no_weak_card_when_all_mastered(self):
        for i in range(1, 6):
            self.add_attempt(True, ["词汇"], n=i)
        data = self.client.get("/api/today", headers=AUTH).json()
        self.assertEqual([a for a in data["actions"] if a["kind"] == "weak"], [])
        totals = self.client.get("/api/knowledge", headers=AUTH).json()["totals"]
        # 展示语义仍保留：最低的 ready 类目
        self.assertEqual(totals["weakest"]["name"], "词汇")

    def test_totals_weakest_has_attempts(self):
        for i in range(1, 6):
            self.add_attempt(False, ["阅读"], n=i)
        totals = self.client.get("/api/knowledge", headers=AUTH).json()["totals"]
        self.assertEqual(totals["weakest"]["name"], "阅读")
        self.assertEqual(totals["weakest"]["attempts"], 5)

    def test_study_today_returns_weak_points_and_prompt(self):
        for i in range(1, 6):
            self.add_attempt(False, ["阅读"], n=i)
        data = self.client.get("/api/study/today", headers=AUTH).json()
        self.assertEqual(data["weak_points"][0]["name"], "阅读")
        self.assertEqual(data["quiz_focus"], "")
        self.assertIn("【本轮重点】", data["quiz_prompt"])
        self.assertIn("阅读", data["quiz_prompt"])

    def test_weak_only_quiz_works_without_today_context(self):
        for i in range(1, 6):
            self.add_attempt(False, ["阅读"], n=i)
        data = self.client.get(
            "/api/study/today", params={"focus": "阅读"}, headers=AUTH).json()
        self.assertEqual(data["stats"]["asks"], 0)
        self.assertEqual(data["stats"]["transcripts"], 0)
        self.assertIn("没有新的学习记录", data["quiz_prompt"])
        self.assertIn("通识自测题", data["quiz_prompt"])

    def test_focus_valid(self):
        for i in range(1, 6):
            self.add_attempt(False, ["阅读"], n=i)
        data = self.client.get(
            "/api/study/today", params={"focus": "语法"}, headers=AUTH).json()
        self.assertEqual(data["quiz_focus"], "语法")
        self.assertIn("本轮指定重点", data["quiz_prompt"])
        self.assertIn("「语法」", data["quiz_prompt"])

    def test_focus_rejects_unknown_and_other(self):
        for text in ("<script>alert(1)</script>", "其他", "不存在的类目", "x" * 50):
            data = self.client.get(
                "/api/study/today", params={"focus": text}, headers=AUTH).json()
            self.assertEqual(data["quiz_focus"], "", text)
            self.assertNotIn("本轮指定重点", data["quiz_prompt"], text)
            self.assertNotIn("<script>", data["quiz_prompt"], text)


if __name__ == "__main__":
    unittest.main()
