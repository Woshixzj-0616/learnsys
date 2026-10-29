# -*- coding: utf-8 -*-
"""P28.2 编程类目：13 类目、旧库补行、编程 BKT、今日 focus。

这些测试在实现前必须失败。失败点应当指向“编程类目还没接上”，
而不是测试自身写错——每个用例只依赖现有公开入口（CATEGORIES /
normalize_points / prompt_rules / store.connect / services.add_attempt / HTTP）。
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.agent.tools.schemas import SAVE_WRONGBOOK_SCHEMA
from learnsys.knowledge import CATEGORIES, normalize_points, prompt_rules
from learnsys.server.app import create_app
from learnsys.services import knowledge as service

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}

ENGLISH_NAMES = ["词汇", "语音", "语法", "听力细节", "听力主旨", "听力推断", "阅读"]
PROGRAMMING_NAMES = ["数据结构", "算法", "C/C++", "计算机网络", "操作系统"]


class CategoryConstantsTest(unittest.TestCase):
    def test_english_and_programming_categories_share_one_list(self):
        names = [c["name"] for c in CATEGORIES]
        self.assertEqual(names[:7], ENGLISH_NAMES)
        self.assertEqual(names[7:12], PROGRAMMING_NAMES)
        self.assertEqual(names[-1], "其他")
        # 「其他」永远是兜底，排在所有真实类目之后。
        self.assertEqual(len(names), 13)

    def test_kinds_are_unique_and_sorts_keep_other_last(self):
        kinds = [c["kind"] for c in CATEGORIES]
        self.assertEqual(len(kinds), len(set(kinds)))
        by_name = {c["name"]: int(c["sort"]) for c in CATEGORIES}
        for name in PROGRAMMING_NAMES:
            self.assertLess(by_name[name], by_name["其他"])
        self.assertGreater(by_name["数据结构"], by_name["阅读"])


class AliasNormalizeTest(unittest.TestCase):
    def test_programming_aliases(self):
        self.assertEqual(
            normalize_points("链表、动态规划、指针")[0],
            ["数据结构", "算法", "C/C++"])
        self.assertEqual(
            normalize_points("死锁、进程")[0],
            ["操作系统"])
        self.assertEqual(
            normalize_points("C语言、哈希表")[0],
            ["C/C++", "数据结构"])

    def test_network_aliases_are_case_insensitive(self):
        for raw in ("TCP、UDP", "tcp、udp", "Tcp、Udp"):
            self.assertEqual(normalize_points(raw)[0], ["计算机网络"], raw)
        self.assertEqual(normalize_points("HTTP、DNS")[0], ["计算机网络"])
        self.assertEqual(normalize_points("网络、路由")[0], ["计算机网络"])

    def test_english_categories_are_not_polluted(self):
        self.assertEqual(normalize_points("生词、连读")[0], ["词汇", "语音"])
        self.assertEqual(normalize_points("语法、阅读")[0], ["语法", "阅读"])
        self.assertEqual(normalize_points("完全看不懂"), (["其他"], "fallback"))
        self.assertEqual(normalize_points(""), (["其他"], "fallback"))


class PromptAndToolContractTest(unittest.TestCase):
    def test_prompt_rules_list_both_subjects(self):
        text = prompt_rules()
        for name in [*ENGLISH_NAMES, *PROGRAMMING_NAMES, "其他"]:
            self.assertIn(name, text)
        self.assertIn("同一学科", text)
        self.assertIn("英语题", text)
        self.assertIn("编程题", text)
        self.assertNotIn("这 8 个类目", text)

    def test_save_wrongbook_schema_lists_programming_categories(self):
        desc = SAVE_WRONGBOOK_SCHEMA["input_schema"]["properties"]["tags"]["description"]
        for name in PROGRAMMING_NAMES:
            self.assertIn(name, desc)
        self.assertIn("同一学科", desc)

    def test_quiz_prompt_keeps_marking_contract(self):
        text = prompt_rules()
        self.assertIn("【知识点】", text)
        self.assertIn("【批改】正确", text)
        self.assertIn("【批改】错误", text)


class SeedRowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"

    def names(self):
        conn = store.connect(self.db)
        try:
            return [r[0] for r in conn.execute(
                "SELECT name FROM knowledge_points ORDER BY sort, id").fetchall()]
        finally:
            conn.close()

    def make_old_db(self):
        """把库还原成 P28.1 的样子：8 个类目、无种子版本标记。"""
        conn = store.connect(self.db)
        try:
            marks = ",".join("?" for _ in PROGRAMMING_NAMES)
            conn.execute(
                f"DELETE FROM knowledge_points WHERE name IN ({marks})",
                tuple(PROGRAMMING_NAMES))
            conn.execute("DELETE FROM meta WHERE key = 'knowledge_seed_version'")
            conn.commit()
        finally:
            conn.close()

    def test_reopen_old_db_adds_programming_categories(self):
        """结账点：已有 v13 库重新打开也要长出 5 个编程类目。

        旧实现把 `_seed_knowledge()` 放在“版本不一致”的分支里，
        `user_version` 已是 13 时直接 return，这 5 行永远不会补。
        """
        self.make_old_db()
        # 用裸连接看旧库：store.connect 会立刻补种，看不到“补种前”的样子。
        with sqlite3.connect(str(self.db)) as raw:
            before = raw.execute(
                "SELECT id, name, created_at FROM knowledge_points ORDER BY id").fetchall()
        self.assertEqual(len(before), 8)     # 确实是旧库

        second = self.names()
        self.assertEqual(len(second), 13)
        for name in PROGRAMMING_NAMES:
            self.assertIn(name, second)

        conn = store.connect(self.db)
        try:
            after = conn.execute(
                "SELECT id, name, created_at FROM knowledge_points ORDER BY id").fetchall()
        finally:
            conn.close()
        self.assertEqual([tuple(r) for r in after[:len(before)]],
                         [tuple(r) for r in before])

    def test_seed_is_idempotent_and_old_rows_unchanged(self):
        conn = store.connect(self.db)
        try:
            before = conn.execute(
                "SELECT id, name, created_at FROM knowledge_points ORDER BY id").fetchall()
        finally:
            conn.close()

        self.names()
        self.names()

        conn = store.connect(self.db)
        try:
            after = conn.execute(
                "SELECT id, name, created_at FROM knowledge_points ORDER BY id").fetchall()
            count = conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual([tuple(r) for r in after[:len(before)]],
                         [tuple(r) for r in before])
        self.assertEqual(int(count), 13)

    def test_seed_version_marker_exists(self):
        conn = store.connect(self.db)
        try:
            marker = store.meta_value(conn, "knowledge_seed_version")
        finally:
            conn.close()
        self.assertTrue(marker, "缺少 knowledge_seed_version，无法判断要不要补种")

    def test_old_attempts_and_wrong_tags_are_not_retagged(self):
        conn = store.connect(self.db)
        try:
            service.add_attempt(
                conn, conversation_id=1, question="旧英语题",
                my_answer="He agrees.", correct=True, points=["词汇"])
            item_id, _ = store.add_wrong_item(
                conn, question="旧代码题：链表反转", answer="", my_answer="",
                tags="指针", source="code",
                source_id="code:1:0123456789abcdef")
            wrong_before = conn.execute(
                "SELECT tags FROM wrong_items WHERE id = ?", (item_id,)).fetchone()[0]
            attempts_before = conn.execute(
                "SELECT COUNT(*) FROM quiz_attempts").fetchone()[0]
            points_before = conn.execute(
                "SELECT kp.name FROM attempt_points ap "
                "JOIN knowledge_points kp ON kp.id = ap.point_id").fetchall()
        finally:
            conn.close()

        self.make_old_db()           # 还原成 P28.1 的 8 类目库
        self.names()                 # 重新打开：只补类目行

        conn = store.connect(self.db)
        try:
            wrong_after = conn.execute(
                "SELECT tags FROM wrong_items WHERE id = ?", (item_id,)).fetchone()[0]
            attempts_after = conn.execute(
                "SELECT COUNT(*) FROM quiz_attempts").fetchone()[0]
            points_after = conn.execute(
                "SELECT kp.name FROM attempt_points ap "
                "JOIN knowledge_points kp ON kp.id = ap.point_id").fetchall()
        finally:
            conn.close()
        self.assertEqual(wrong_after, "指针")
        self.assertEqual(wrong_before, wrong_after)
        self.assertEqual(attempts_after, attempts_before)
        self.assertEqual([tuple(r) for r in points_after],
                         [tuple(r) for r in points_before])


class ProgrammingBktTest(unittest.TestCase):
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

    def test_programming_points_are_modeled_not_fallback(self):
        result = self.add("数据结构", True)
        self.assertEqual(result["points"], ["数据结构"])
        self.assertEqual(result["points_source"], "model")
        self.assertTrue(result["parse_ok"])

    def test_five_programming_attempts_become_mastery(self):
        for _ in range(5):
            self.add("算法", True)
        point, data = self.point("算法")
        self.assertTrue(point["mastery_ready"])
        self.assertEqual(point["mastery_attempts"], 5)
        self.assertEqual(point["mastery_level"], "掌握")
        self.assertEqual(data["totals"]["mastery_ready_points"], 1)
        self.assertAlmostEqual(
            data["totals"]["average_mastery"], point["mastery"], places=4)

    def test_five_wrong_programming_attempts_are_weakest(self):
        for _ in range(5):
            self.add("操作系统", False)
        point, data = self.point("操作系统")
        self.assertTrue(point["mastery_ready"])
        self.assertEqual(point["mastery_level"], "薄弱")
        self.assertEqual(data["totals"]["weakest"]["name"], "操作系统")

    def test_mixed_programming_points_share_one_attempt(self):
        service.add_attempt(
            self.conn, conversation_id=9, question="多类目代码题",
            my_answer="答案", correct=False, points=["数据结构", "算法"])
        first, _ = self.point("数据结构")
        second, _ = self.point("算法")
        self.assertEqual(first["mastery_attempts"], 1)
        self.assertEqual(second["mastery_attempts"], 1)
        self.assertEqual(
            service.attempt_stats(self.conn)["totals"]["attempts"], 1)


class TodayFocusTest(unittest.TestCase):
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

    def test_focus_accepts_programming_category(self):
        for i in range(1, 6):
            service.add_attempt(
                self.conn, conversation_id=i, question=f"第 {i} 题：算法",
                my_answer=f"答案 {i}", correct=False, points=["算法"])
        data = self.client.get(
            "/api/study/today", params={"focus": "算法"}, headers=AUTH).json()
        self.assertEqual(data["quiz_focus"], "算法")
        self.assertIn("本轮指定重点", data["quiz_prompt"])
        self.assertIn("「算法」", data["quiz_prompt"])

    def test_focus_still_rejects_other_and_unknown(self):
        for text in ("其他", "不存在的类目"):
            data = self.client.get(
                "/api/study/today", params={"focus": text}, headers=AUTH).json()
            self.assertEqual(data["quiz_focus"], "", text)
            self.assertNotIn("本轮指定重点", data["quiz_prompt"], text)


if __name__ == "__main__":
    unittest.main()
