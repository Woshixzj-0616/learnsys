# -*- coding: utf-8 -*-
"""P27.1 服务层：三域装配、空数据不炸、学习字段与 /api/today 同源。"""
from __future__ import annotations

import datetime as dt
import unittest

from learnsys import store
from learnsys.context import MAX_PERSONAL_STATE
from learnsys.services import home
from learnsys.services import today as today_service


def _today() -> str:
    return dt.date.today().isoformat()


class TestHomePayload(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.day = _today()

    def test_empty_database_returns_three_domains(self):
        data = home.payload(self.conn, self.day)
        self.assertEqual(set(data), {"date", "learning", "work", "life"})
        self.assertEqual(data["date"], self.day)
        self.assertEqual(data["learning"]["done"], 0)
        self.assertEqual(data["learning"]["total"], 3)
        self.assertEqual(data["learning"]["due_reviews"], 0)
        self.assertEqual(data["learning"]["recent_wrong"], [])
        self.assertEqual(data["work"]["projects"], [])
        self.assertEqual(data["work"]["running"], 0)
        self.assertEqual(data["work"]["queued"], 0)
        self.assertEqual(data["life"]["cards"], [])
        self.assertEqual(data["life"]["subscriptions"], [])
        self.assertEqual(data["life"]["events"], [])

    def test_domain_hrefs_are_the_single_source(self):
        data = home.payload(self.conn, self.day)
        self.assertEqual(data["learning"]["href"], "#/cet6")
        self.assertEqual(data["work"]["href"], "#/agents")
        self.assertEqual(data["life"]["href"], "#/briefing")

        item_id, _ = store.add_wrong_item(self.conn, question="到期题")
        two_days_ago = (dt.date.today() - dt.timedelta(days=2)).isoformat()
        self.conn.execute("UPDATE wrong_items SET ts = ? WHERE id = ?",
                          (f"{two_days_ago} 10:00:00", item_id))
        self.conn.commit()
        data = home.payload(self.conn, self.day)
        self.assertGreaterEqual(data["learning"]["due_reviews"], 1)
        self.assertEqual(data["learning"]["href"], "#/review",
                         "有到期复习时学习卡直接进复习页")

    def test_seeded_domains(self):
        store.add_wrong_item(self.conn, question="二叉树的前序遍历怎么写",
                             answer="根左右")
        store.upsert_project(
            self.conn, name="学习工作台", repo_path="D:/Desktop/learnsys",
            next_step="完成 P27.1")
        store.upsert_subscription(
            self.conn, topic="AI 新闻", kind="news", cadence="daily",
            at_time="00:00")
        store.upsert_card(
            self.conn, day=self.day, domain="life", title="今晚早睡",
            content={"text": "23:00 前"})
        store.add_event(self.conn, "life", "todo", "交水电费")

        data = home.payload(self.conn, self.day)
        self.assertEqual(data["learning"]["recent_wrong"][0]["question"],
                         "二叉树的前序遍历怎么写")
        self.assertEqual(data["work"]["projects"][0]["name"], "学习工作台")
        self.assertEqual(data["work"]["next_step"], "完成 P27.1")
        self.assertEqual(data["life"]["cards"][0]["title"], "今晚早睡")
        self.assertEqual(data["life"]["subscriptions"][0]["topic"], "AI 新闻")
        self.assertEqual([item["title"] for item in data["life"]["events"]],
                         ["交水电费"])

    def test_recent_wrong_is_unmastered_and_capped_at_three(self):
        ids = []
        for index in range(5):
            item_id, _ = store.add_wrong_item(
                self.conn, question=f"错题{index}", answer="")
            ids.append(item_id)
        store.set_wrong_mastered(self.conn, ids[-1], True)
        data = home.payload(self.conn, self.day)
        questions = [item["question"]
                     for item in data["learning"]["recent_wrong"]]
        self.assertEqual(questions, ["错题3", "错题2", "错题1"])

    def test_learning_fields_match_today_payload(self):
        store.add_wrong_item(self.conn, question="链表怎么插入", answer="改指针")
        store.add_breakpoint_events(
            self.conn, stamp=f"{self.day} 10:00:00", paper_id="paper-1",
            paper="2025 年 6 月", section="听力", item="长对话",
            sentences=[{"sentence": 3, "tags": ["连读"], "note": "",
                        "loops": 2}])

        today = today_service.payload(self.conn, self.day)
        data = home.payload(self.conn, self.day)
        self.assertEqual(data["learning"]["due_reviews"], today["due_reviews"])
        self.assertEqual(data["learning"]["cet6"], today["cet6"])
        self.assertEqual(data["learning"]["cet6"][0]["paper"], "2025 年 6 月")


class TestAgentState(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.day = _today()

    def test_empty_state_uses_placeholder_and_stays_under_cap(self):
        text = home.agent_state(self.conn, self.day)
        self.assertLessEqual(len(text), MAX_PERSONAL_STATE)
        self.assertIn("学习：今日 0/3", text)
        self.assertIn("项目：暂无", text)
        self.assertIn("生活：暂无", text)

    def test_fixed_order_and_content_limits(self):
        long_question = "错" * 60
        store.add_wrong_item(self.conn, question=long_question, answer="")
        for index, name in enumerate(("项目甲", "项目乙", "项目丙")):
            store.upsert_project(self.conn, name=name,
                                 next_step=f"下一步{index}")
        store.upsert_subscription(
            self.conn, topic="AI 新闻", cadence="daily", at_time="00:00")

        text = home.agent_state(self.conn, self.day)
        self.assertLessEqual(len(text), MAX_PERSONAL_STATE)
        positions = [text.index(label) for label in
                     ("学习：", "复习：", "项目：", "生活：")]
        self.assertEqual(positions, sorted(positions), "个人状态顺序必须固定")
        self.assertIn("错" * 40, text)
        self.assertNotIn("错" * 41, text, "卡点题干只写前 40 字")
        present = [name for name in ("项目甲", "项目乙", "项目丙") if name in text]
        self.assertEqual(len(present), 2, "项目最多写 2 个")
        self.assertIn("AI 新闻", text)

    def test_long_state_is_clipped(self):
        for index in range(5):
            store.upsert_project(
                self.conn, name=f"项目{index}" + "长" * 120,
                next_step="很长的下一步" * 30)
        text = home.agent_state(self.conn, self.day)
        self.assertLessEqual(len(text), MAX_PERSONAL_STATE)
        self.assertTrue(text.endswith("…"))


if __name__ == "__main__":
    unittest.main()
