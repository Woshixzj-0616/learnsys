# -*- coding: utf-8 -*-
"""P30.2 生活事务箱：store CRUD、到期筛选、计数与状态机。"""
from __future__ import annotations

import datetime as dt
import unittest

from learnsys import store
from learnsys.services.life import items as item_service

DAY = "2026-10-30"


class LifeItemsStoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_add_and_list_default_open(self):
        item = store.add_life_item(
            self.conn, title="交房租", due_date=DAY, note="支付宝")
        self.assertGreater(item["id"], 0)
        self.assertEqual(item["kind"], "todo")
        self.assertEqual(item["status"], "open")
        self.assertEqual(item["due_date"], DAY)
        self.assertEqual(item["note"], "支付宝")
        self.assertEqual(store.list_life_items(self.conn), [item])

    def test_empty_title_is_rejected(self):
        with self.assertRaises(ValueError):
            store.add_life_item(self.conn, title="   ")
        with self.assertRaises(ValueError):
            store.add_life_item(self.conn, title="x", kind="unknown")

    def test_habit_keeps_one_line_value(self):
        item = store.add_life_item(
            self.conn, title="起床", kind="habit", value="07:10 起床")
        self.assertEqual(item["kind"], "habit")
        self.assertEqual(item["value"], "07:10 起床")

    def test_due_items_excludes_future_and_empty(self):
        store.add_life_item(self.conn, title="今天", due_date=DAY)
        store.add_life_item(self.conn, title="昨天", due_date="2026-10-29")
        store.add_life_item(self.conn, title="明天", due_date="2026-10-31")
        store.add_life_item(self.conn, title="不限期")
        due = store.due_life_items(self.conn, DAY)
        self.assertEqual([item["title"] for item in due], ["昨天", "今天"])

    def test_counts_open_overdue_done(self):
        store.add_life_item(self.conn, title="今天", due_date=DAY)
        store.add_life_item(self.conn, title="昨天", due_date="2026-10-29")
        store.add_life_item(self.conn, title="无期限")
        counts = store.life_item_counts(self.conn, DAY)
        self.assertEqual(counts, {"open": 3, "overdue": 1, "done": 0})

    def test_update_whitelist(self):
        item = store.add_life_item(self.conn, title="买牛奶")
        updated = store.update_life_item(
            self.conn, item["id"], title="买酸奶", due_date=DAY, note="超市")
        self.assertEqual(updated["title"], "买酸奶")
        self.assertEqual(updated["due_date"], DAY)
        self.assertEqual(updated["note"], "超市")
        with self.assertRaises(ValueError):
            store.update_life_item(self.conn, item["id"], title="")

    def test_status_machine(self):
        item = store.add_life_item(self.conn, title="交房租")
        done = item_service.change_status(self.conn, item["id"], "done")
        self.assertEqual(done["status"], "done")
        self.assertTrue(done["done_at"])
        reopened = item_service.change_status(self.conn, item["id"], "open")
        self.assertEqual(reopened["status"], "open")
        self.assertEqual(reopened["done_at"], "")
        archived = item_service.change_status(self.conn, item["id"], "archived")
        self.assertEqual(archived["status"], "archived")
        with self.assertRaises(ValueError):
            item_service.change_status(self.conn, item["id"], "done")

    def test_delete(self):
        item = store.add_life_item(self.conn, title="临时")
        self.assertIsNotNone(store.delete_life_item(self.conn, item["id"]))
        self.assertIsNone(store.get_life_item(self.conn, item["id"]))


class LifeItemsServiceTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_validate_due_date(self):
        item_service.validate("todo", DAY)
        item_service.validate("habit", "")
        with self.assertRaises(ValueError):
            item_service.validate("todo", "10-30")
        with self.assertRaises(ValueError):
            item_service.validate("todo", "2026-13-01")

    def test_summary_and_reminders_order(self):
        store.add_life_item(self.conn, title="昨天的事",
                            due_date="2026-10-29")
        store.add_life_item(self.conn, title="今天的事", due_date=DAY)
        data = item_service.summary(self.conn, DAY)
        self.assertEqual(data["item_count"], 2)
        self.assertEqual(data["overdue_count"], 1)
        lines = item_service.reminder_lines(self.conn, DAY, limit=2)
        self.assertEqual(lines[0], "待办：昨天的事（逾期 1 天）")
        self.assertEqual(lines[1], "待办：今天的事（今天）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
