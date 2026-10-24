# -*- coding: utf-8 -*-
"""知识点与全量答题流水：8 类目、归一、落库、统计、BKT-ready、回填。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.agent import prompts, selfcheck
from learnsys.services import study
from learnsys.knowledge import CATEGORIES, normalize_points, prompt_rules
from learnsys.server.app import create_app
from learnsys.services import knowledge as service

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class KnowledgeConstantsTest(unittest.TestCase):
    def test_eight_categories(self):
        names = [c["name"] for c in CATEGORIES]
        self.assertEqual(names, ["词汇", "语音", "语法", "听力细节", "听力主旨",
                                 "听力推断", "阅读", "其他"])

    def test_aliases_and_fallback(self):
        self.assertEqual(normalize_points("生词、连读")[0], ["词汇", "语音"])
        self.assertEqual(normalize_points(["句法", "细节", "阅读"])[0],
                         ["语法", "听力细节", "阅读"])
        self.assertEqual(normalize_points("完全看不懂"), (["其他"], "fallback"))
        self.assertEqual(normalize_points(""), (["其他"], "fallback"))

    def test_prompt_rules_include_contract(self):
        text = prompt_rules()
        for name in ("词汇", "语音", "语法", "听力细节", "听力主旨",
                     "听力推断", "阅读", "其他"):
            self.assertIn(name, text)
        self.assertIn("【知识点】", text)
        self.assertIn("【批改】正确", text)
        self.assertIn("【批改】错误", text)


class PromptContractTest(unittest.TestCase):
    def test_quiz_builders_and_system_share_contract(self):
        material = {"id": 1, "title": "测试资料", "body": "正文"}
        texts = [study.build_quiz_question([], [], ""),
                 study.build_material_quiz_question(material),
                 prompts.build_system("quiz")]
        for text in texts:
            self.assertIn("【知识点】", text)
            self.assertIn("【批改】正确", text)
            self.assertIn("【批改】错误", text)
            for name in ("词汇", "语音", "语法", "听力细节", "听力主旨",
                         "听力推断", "阅读", "其他"):
                self.assertIn(name, text)
        self.assertIn("save_wrongbook", texts[0])
        self.assertIn("save_wrongbook", texts[1])

    def test_rewrite_keeps_markers(self):
        self.assertIn("【知识点】", selfcheck.REWRITE_SYSTEM)
        self.assertIn("【批改】", selfcheck.REWRITE_SYSTEM)


class KnowledgeDbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)

    def add(self, **kw):
        base = dict(conversation_id=1, material_id=0, question_no=1,
                    question="The speaker implies what?", my_answer="He agrees.",
                    correct=True, feedback="对", points=["听力推断"])
        base.update(kw)
        return service.add_attempt(self.conn, **base)

    def test_seed_is_idempotent_and_meta_exists(self):
        rows = self.conn.execute(
            "SELECT name FROM knowledge_points ORDER BY sort").fetchall()
        self.assertEqual([r[0] for r in rows], [c["name"] for c in CATEGORIES])
        self.assertTrue(store.meta_value(self.conn, "knowledge_attempts_since"))
        store.connect(self.db).close()
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM knowledge_points").fetchone()[0], 8)

    def test_attempt_stats_and_bkt_ready(self):
        first = self.add()
        self.assertTrue(first["created"])
        self.assertEqual(first["points"], ["听力推断"])
        self.assertTrue(first["parse_ok"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM attempt_points").fetchone()[0], 1)
        stats = service.attempt_stats(self.conn)
        row = next(p for p in stats["points"] if p["name"] == "听力推断")
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["quiz_known"], 1)
        self.assertEqual(row["quiz_correct"], 1)
        self.assertEqual(row["accuracy"], 1.0)
        self.assertEqual(row["bkt_ready"], 1)
        self.assertEqual(stats["totals"]["bkt_ready"], 1)

    def test_duplicate_is_idempotent_but_other_conversation_counts(self):
        first = self.add()
        again = self.add()
        self.assertFalse(again["created"])
        self.assertEqual(again["id"], first["id"])
        other = self.add(conversation_id=2)
        self.assertTrue(other["created"])
        self.assertEqual(service.attempt_stats(self.conn)["totals"]["attempts"], 2)

    def test_unknown_correct_and_fallback_points_are_not_bkt_ready(self):
        unknown = self.add(correct=None)
        self.assertFalse(unknown["parse_ok"])
        fallback = self.add(points=[], my_answer="别的答案")
        self.assertEqual(fallback["points"], ["其他"])
        self.assertEqual(fallback["points_source"], "fallback")
        self.assertFalse(fallback["parse_ok"])
        stats = service.attempt_stats(self.conn)
        self.assertEqual(stats["totals"]["bkt_ready"], 0)
        self.assertEqual(stats["totals"]["quiz_known"], 1)   # 只有 fallback 那条判了对错

    def test_more_than_three_points_is_truncated_and_not_parse_ok(self):
        result = self.add(points=["词汇", "语音", "语法", "阅读"])
        self.assertEqual(result["points"], ["词汇", "语音", "语法"])
        self.assertFalse(result["parse_ok"])
        self.assertEqual(service.attempt_stats(self.conn)["totals"]["bkt_ready"], 0)

    def test_point_attempts_and_unknown_point(self):
        self.add()
        point = next(p for p in service.attempt_stats(self.conn)["points"]
                     if p["name"] == "听力推断")
        data = service.point_attempts(self.conn, point["id"], limit=10)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["points"], ["听力推断"])
        self.assertIsNone(service.point_attempts(self.conn, 9999))

    def test_days_filter(self):
        self.add()
        self.conn.execute(
            "UPDATE quiz_attempts SET day='2026-01-01', ts='2026-01-01 08:00:00'")
        self.conn.commit()
        self.assertEqual(service.attempt_stats(self.conn, days=7)["totals"]["attempts"], 0)


class MasteryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)
        self.n = 0

    def add(self, point, correct, **kw):
        self.n += 1
        return service.add_attempt(
            self.conn, conversation_id=kw.pop("conversation_id", 1),
            question=f"第 {self.n} 题：{point}", my_answer=f"答案-{self.n}",
            correct=correct, points=[point], **kw)

    def point(self, name, **kw):
        data = service.attempt_stats(self.conn, **kw)
        return next(p for p in data["points"] if p["name"] == name), data

    def test_five_correct_is_mastered(self):
        for _ in range(5):
            self.add("词汇", True)
        point, data = self.point("词汇")
        self.assertTrue(point["mastery_ready"])
        self.assertGreater(point["mastery"], 0.99)
        self.assertEqual(point["mastery_attempts"], 5)
        self.assertEqual(point["mastery_level"], "掌握")
        self.assertEqual(data["totals"]["mastery_ready_points"], 1)
        self.assertAlmostEqual(data["totals"]["average_mastery"], point["mastery"], places=4)
        self.assertEqual(data["totals"]["weakest"]["name"], "词汇")

    def test_four_is_not_enough(self):
        for _ in range(4):
            self.add("语法", True)
        point, data = self.point("语法")
        self.assertFalse(point["mastery_ready"])
        self.assertIsNone(point["mastery"])
        self.assertEqual(point["mastery_attempts"], 4)
        self.assertEqual(point["mastery_level"], "样本不足")
        self.assertEqual(data["totals"]["mastery_ready_points"], 0)
        self.assertIsNone(data["totals"]["average_mastery"])
        self.assertIsNone(data["totals"]["weakest"])

    def test_five_wrong_is_weak(self):
        for _ in range(5):
            self.add("阅读", False)
        point, _ = self.point("阅读")
        self.assertTrue(point["mastery_ready"])
        self.assertLess(point["mastery"], 0.2)
        self.assertEqual(point["mastery_level"], "薄弱")
        self.assertEqual(point["accuracy"], 0.0)

    def test_order_sensitive(self):
        for correct in (True, True, False, True, False):
            self.add("语音", correct)
        for correct in (False, True, False, True, True):
            self.add("听力细节", correct)
        voice, _ = self.point("语音")
        detail, _ = self.point("听力细节")
        self.assertTrue(voice["mastery_ready"])
        self.assertTrue(detail["mastery_ready"])
        self.assertNotEqual(voice["mastery"], detail["mastery"])

    def test_multiple_points_share_one_attempt(self):
        service.add_attempt(
            self.conn, conversation_id=9, question="多类目题", my_answer="答案",
            correct=True, points=["词汇", "语法"])
        vocab, _ = self.point("词汇")
        grammar, _ = self.point("语法")
        self.assertEqual(vocab["mastery_attempts"], 1)
        self.assertEqual(grammar["mastery_attempts"], 1)
        self.assertEqual(service.attempt_stats(self.conn)["totals"]["attempts"], 1)

    def test_other_is_not_modeled(self):
        for _ in range(5):
            self.add("其他", True)
        point, data = self.point("其他")
        self.assertEqual(point["bkt_ready"], 5)
        self.assertIsNone(point["mastery"])
        self.assertEqual(point["mastery_attempts"], 0)
        self.assertEqual(point["mastery_level"], "不建模")
        self.assertEqual(data["totals"]["mastery_ready_points"], 0)
        self.assertIsNone(data["totals"]["average_mastery"])

    def test_fallback_and_unknown_correct_do_not_enter_bkt(self):
        for _ in range(5):
            self.add("词汇", True)
        before, _ = self.point("词汇")
        service.add_attempt(self.conn, question="无知识点", my_answer="a",
                            correct=True, points=[])
        service.add_attempt(self.conn, question="未判定", my_answer="b",
                            correct=None, points=["词汇"])
        service.add_attempt(self.conn, question="四点", my_answer="c",
                            correct=True, points=["词汇", "语音", "语法", "阅读"])
        after, _ = self.point("词汇")
        self.assertEqual(after["mastery_attempts"], before["mastery_attempts"])
        self.assertEqual(after["mastery"], before["mastery"])
        self.assertEqual(after["bkt_ready"], before["bkt_ready"])

    def test_days_window_recomputes(self):
        for _ in range(5):
            self.add("词汇", True)
        self.conn.execute("UPDATE quiz_attempts SET day='2026-01-01', ts='2026-01-01 08:00:00'")
        self.conn.commit()
        recent, _ = self.point("词汇", days=7)
        self.assertIsNone(recent["mastery"])
        self.assertEqual(recent["mastery_level"], "未开始")
        alltime, _ = self.point("词汇", days=0)
        self.assertTrue(alltime["mastery_ready"])
        self.assertEqual(alltime["mastery_level"], "掌握")

    def test_p18_fields_are_preserved(self):
        self.add("词汇", True)
        point, _ = self.point("词汇")
        for key in ("attempts", "quiz_attempts", "quiz_known", "quiz_correct",
                    "accuracy", "bkt_ready", "backfill", "fallback", "last_ts"):
            self.assertIn(key, point)


class BackfillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)

    def add_wrong(self, question="老题：他什么意思？", tags="生词、细节",
                  source="quiz", ref="7"):
        fingerprint = store.wrong_fingerprint(question)
        item_id, _ = store.add_wrong_item(
            self.conn, question=question, answer="参考答案", my_answer="我的答案",
            tags=tags, source=source, source_id=f"{source}:{ref}:{fingerprint}")
        self.conn.execute(
            "UPDATE wrong_items SET ts='2026-01-01 08:00:00' WHERE id=?", (item_id,))
        self.conn.commit()
        return item_id, fingerprint

    def test_dry_run_then_backfill_and_bkt_ready_unchanged(self):
        item_id, _ = self.add_wrong()
        before = service.attempt_stats(self.conn)["totals"]["bkt_ready"]
        preview = service.backfill_wrong_items(self.conn, dry_run=True)
        self.assertEqual(preview["created"], 1)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM quiz_attempts").fetchone()[0], 0)
        done = service.backfill_wrong_items(self.conn)
        self.assertEqual(done["created"], 1)
        self.assertEqual(done["scanned"], 1)
        row = self.conn.execute(
            "SELECT source, correct, points_source, question, my_answer, ts "
            "FROM quiz_attempts").fetchone()
        self.assertEqual(row[0], "backfill")
        self.assertEqual(row[1], 0)
        self.assertEqual(row[2], "tags")
        self.assertIn("老题", row[3])
        self.assertEqual(row[5], "2026-01-01 08:00:00")
        self.assertEqual(service.attempt_stats(self.conn)["totals"]["bkt_ready"], before)
        again = service.backfill_wrong_items(self.conn)
        self.assertTrue(again["already_done"])
        forced = service.backfill_wrong_items(self.conn, force=True)
        self.assertEqual(forced["created"], 0)
        self.assertEqual(forced["duplicate"], 1)

    def test_non_quiz_and_live_attempt_are_skipped(self):
        self.add_wrong(source="ask", ref="9")
        item_id, fingerprint = self.add_wrong(question="新题", ref="8")
        live = service.add_attempt(
            self.conn, conversation_id=8, question="新题", my_answer="我的答案",
            correct=False, points=["听力细节"])
        self.assertTrue(live["created"])
        data = service.backfill_wrong_items(self.conn, force=True)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["live_skipped"], 1)


class KnowledgeApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        store.connect(self.db).close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))
        self.payload = {
            "conversation_id": 1, "material_id": 0, "question_no": 1,
            "question": "What does the speaker imply?", "my_answer": "He disagrees.",
            "correct": False, "feedback": "推理方向反了",
            "points": ["听力推断"],
        }

    def test_attempt_requires_token_and_validates(self):
        self.assertEqual(
            self.client.post("/api/quiz/attempt", json=self.payload).status_code, 403)
        bad = dict(self.payload, question="")
        self.assertEqual(
            self.client.post("/api/quiz/attempt", json=bad, headers=AUTH).status_code, 400)

    def test_attempt_duplicate_and_stats(self):
        first = self.client.post("/api/quiz/attempt", json=self.payload, headers=AUTH)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["created"])
        again = self.client.post("/api/quiz/attempt", json=self.payload, headers=AUTH)
        self.assertFalse(again.json()["created"])
        stats = self.client.get("/api/knowledge", headers=AUTH)
        self.assertEqual(stats.status_code, 200)
        data = stats.json()
        self.assertEqual(len(data["points"]), 8)
        self.assertEqual(data["totals"]["attempts"], 1)
        self.assertEqual(data["totals"]["bkt_ready"], 1)
        point = next(p for p in data["points"] if p["name"] == "听力推断")
        for key in ("mastery", "mastery_attempts", "mastery_ready", "mastery_level"):
            self.assertIn(key, point)
        self.assertIsNone(point["mastery"])
        self.assertEqual(point["mastery_level"], "样本不足")
        self.assertIn("bkt", data)
        self.assertEqual(data["bkt"]["min_samples"], 5)
        self.assertEqual(data["bkt"]["excluded"], ["其他"])

    def test_point_detail_and_404(self):
        self.client.post("/api/quiz/attempt", json=self.payload, headers=AUTH)
        point = next(p for p in self.client.get(
            "/api/knowledge", headers=AUTH).json()["points"]
            if p["name"] == "听力推断")
        detail = self.client.get(
            f"/api/knowledge/{point['id']}/attempts", headers=AUTH)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["count"], 1)
        self.assertEqual(
            self.client.get("/api/knowledge/9999/attempts", headers=AUTH).status_code, 404)

    def test_backfill_endpoint(self):
        res = self.client.post("/api/knowledge/backfill",
                               json={"dry_run": True}, headers=AUTH)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["created"], 0)


if __name__ == "__main__":
    unittest.main()
