# -*- coding: utf-8 -*-
"""P27.1 store：4 张个人域表的 CRUD、去重与到期口径。"""
from __future__ import annotations

import datetime as dt
import unittest

from learnsys import store


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)


class TestProfileFacts(_DbCase):
    def test_upsert_list_update_archive(self):
        fact = store.upsert_fact(
            self.conn, kind="preference", content="回答用中文",
            evidence="2026-10-29 会话", confidence=0.9)
        self.assertGreater(fact["id"], 0)
        self.assertEqual(fact["status"], "active")
        self.assertAlmostEqual(fact["confidence"], 0.9)
        self.assertEqual([row["id"] for row in store.list_facts(self.conn)],
                         [fact["id"]])

        updated = store.upsert_fact(
            self.conn, fact_id=fact["id"], kind="goal", content="每周复盘三次")
        self.assertEqual(updated["kind"], "goal")
        self.assertEqual(updated["content"], "每周复盘三次")
        self.assertEqual(len(store.list_facts(self.conn)), 1,
                         "按 id 更新不应新增一条")

        archived = store.archive_fact(self.conn, fact["id"])
        self.assertIsNotNone(archived)
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(store.list_facts(self.conn), [])
        self.assertEqual(len(store.list_facts(self.conn, status="archived")), 1)
        self.assertIsNone(store.archive_fact(self.conn, 99999))

    def test_list_filters_by_kind(self):
        store.upsert_fact(self.conn, kind="preference", content="偏好")
        store.upsert_fact(self.conn, kind="constraint", content="约束")
        rows = store.list_facts(self.conn, kind="preference")
        self.assertEqual([row["content"] for row in rows], ["偏好"])


class TestProjects(_DbCase):
    def test_upsert_by_name_and_next_step(self):
        first = store.upsert_project(
            self.conn, name="学习工作台", repo_path="D:/Desktop/learnsys",
            next_step="完成 P27.1")
        again = store.upsert_project(
            self.conn, name="学习工作台", repo_path="D:/Desktop/learnsys",
            next_step="做 P27.2", risk="今日页变长")
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(len(store.list_projects(self.conn)), 1)
        self.assertEqual(again["next_step"], "做 P27.2")
        self.assertEqual(again["risk"], "今日页变长")

        changed = store.set_next_step(self.conn, again["id"], "验收 P27.2")
        self.assertEqual(changed["next_step"], "验收 P27.2")
        self.assertIsNone(store.set_next_step(self.conn, 99999, "无"))

    def test_status_filter(self):
        store.upsert_project(self.conn, name="A", status="active")
        store.upsert_project(self.conn, name="B", status="paused")
        self.assertEqual(
            {p["name"] for p in store.list_projects(self.conn)}, {"A", "B"})
        self.assertEqual(
            [p["name"] for p in store.list_projects(self.conn, status="paused")],
            ["B"])


class TestSubscriptions(_DbCase):
    def setUp(self):
        super().setUp()
        self.moment = dt.datetime(2026, 10, 29, 8, 0, 0)

    def test_upsert_dedupes_topic_and_kind(self):
        first = store.upsert_subscription(
            self.conn, topic="AI 新闻", kind="news", cadence="daily",
            at_time="07:30", sources=["https://example.com/rss"])
        again = store.upsert_subscription(
            self.conn, topic="AI 新闻", kind="news", cadence="weekly",
            at_time="08:00", sources=[])
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(len(store.list_subscriptions(self.conn)), 1)
        self.assertEqual(again["cadence"], "weekly")
        self.assertEqual(again["sources"], [])
        self.assertEqual(again["last_run"], "")

    def test_daily_and_weekly_due_rules(self):
        daily = store.upsert_subscription(
            self.conn, topic="每日英语", cadence="daily", at_time="07:30")
        weekly = store.upsert_subscription(
            self.conn, topic="每周总结", cadence="weekly", at_time="07:30")
        self.assertEqual(
            {row["id"] for row in store.due_subscriptions(self.conn, at=self.moment)},
            {daily["id"], weekly["id"]})

        store.mark_run(self.conn, daily["id"], ts="2026-10-29 07:30:00")
        store.mark_run(self.conn, weekly["id"], ts="2026-10-25 07:30:00")
        due = store.due_subscriptions(self.conn, at=self.moment)
        self.assertEqual(due, [], "当天跑过的每日订阅和 4 天前跑过的每周订阅都不该到期")

        store.mark_run(self.conn, weekly["id"], ts="2026-10-20 07:30:00")
        due = store.due_subscriptions(self.conn, at=self.moment)
        self.assertEqual([row["id"] for row in due], [weekly["id"]])

    def test_time_of_day_and_disabled(self):
        later = store.upsert_subscription(
            self.conn, topic="九点后", cadence="daily", at_time="09:00")
        self.assertEqual(store.due_subscriptions(self.conn, at=self.moment), [])

        early = store.upsert_subscription(
            self.conn, topic="七点半", cadence="daily", at_time="07:30")
        disabled = store.upsert_subscription(
            self.conn, topic="停用的", cadence="daily", at_time="07:30",
            enabled=False)
        due = store.due_subscriptions(self.conn, at=self.moment)
        self.assertEqual([row["id"] for row in due], [early["id"]])
        self.assertNotIn(later["id"], [row["id"] for row in due])
        self.assertNotIn(disabled["id"], [row["id"] for row in due])

    def test_mark_run_returns_updated_row(self):
        sub = store.upsert_subscription(
            self.conn, topic="价格", kind="price", at_time="07:30")
        updated = store.mark_run(self.conn, sub["id"], ts="2026-10-29 08:05:00")
        self.assertEqual(updated["last_run"], "2026-10-29 08:05:00")
        self.assertIsNone(store.mark_run(self.conn, 99999))


class TestDailyCards(_DbCase):
    def test_upsert_unique_key_and_content(self):
        first = store.upsert_card(
            self.conn, day="2026-10-29", domain="life", title="今日提醒",
            content={"text": "带伞"})
        again = store.upsert_card(
            self.conn, day="2026-10-29", domain="life", title="今日提醒",
            content={"text": "带伞和外套"})
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(again["content"], {"text": "带伞和外套"})
        self.assertEqual(len(store.list_cards(self.conn, day="2026-10-29")), 1)

        store.upsert_card(self.conn, day="2026-10-29", domain="learn",
                          title="复习", content={})
        store.upsert_card(self.conn, day="2026-10-28", domain="life",
                          title="昨天", content={})
        self.assertEqual(
            len(store.list_cards(self.conn, day="2026-10-29", domain="life")), 1)

    def test_mark_read_keeps_read_at_on_upsert(self):
        card = store.upsert_card(
            self.conn, day="2026-10-29", domain="life", title="喝水", content={})
        read = store.mark_read(self.conn, card["id"])
        self.assertTrue(read["read"])
        self.assertTrue(read["read_at"])
        store.upsert_card(
            self.conn, day="2026-10-29", domain="life", title="喝水",
            content={"text": "八杯"})
        rows = store.list_cards(self.conn, day="2026-10-29", domain="life")
        self.assertTrue(rows[0]["read"], "更新内容不能把已读状态清掉")
        self.assertIsNone(store.mark_read(self.conn, 99999))


if __name__ == "__main__":
    unittest.main()
