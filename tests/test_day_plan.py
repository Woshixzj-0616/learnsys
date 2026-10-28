# -*- coding: utf-8 -*-
"""今日三格目标（2026-10-28）：完成判定只看数据库事实。

三格 = 精听 / 训练或复习 / 复盘；时间只做预算，不参与达标。
"""
from __future__ import annotations

import datetime
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys.services import day_plan  # noqa: E402

DAY = "2026-10-28"

SCHEMA = """
CREATE TABLE cet6_events (
    ts TEXT, paper_id TEXT, paper_title TEXT, section TEXT, item TEXT,
    sentence INTEGER);
CREATE TABLE train_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, prompt_id TEXT,
    mode TEXT, status TEXT, duration_s INTEGER, band INTEGER,
    created_at TEXT, updated_at TEXT);
CREATE TABLE events (ts TEXT, module TEXT, kind TEXT);
CREATE TABLE asks (ts TEXT);
CREATE TABLE review_log (ts TEXT);
CREATE TABLE quiz_attempts (ts TEXT, day TEXT);
CREATE TABLE wrong_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, source_id TEXT,
    question TEXT, answer TEXT, my_answer TEXT, tags TEXT, note TEXT,
    auto INTEGER DEFAULT 0, review_stage INTEGER DEFAULT 0,
    last_review TEXT DEFAULT '', mastered INTEGER DEFAULT 0,
    material_id INTEGER DEFAULT 0);
CREATE TABLE review_state (
    item_type TEXT, item_id INTEGER, due TEXT, state TEXT DEFAULT 'new',
    reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0,
    scheduled_days INTEGER DEFAULT 0, PRIMARY KEY (item_type, item_id));
CREATE TABLE materials (id INTEGER PRIMARY KEY, title TEXT);
"""


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def _at(hour: int, sentence: int = 1, item: str = "Recording 1") -> str:
    return f"{DAY} {hour:02d}:00:00"


def _sentence(conn, hour: int, sentence: int) -> None:
    conn.execute(
        "INSERT INTO cet6_events VALUES (?, '卷一', '测试卷', 'Section C', ?, ?)",
        (_at(hour), "Recording 1", sentence))
    conn.commit()


def _writing(conn) -> None:
    conn.execute(
        "INSERT INTO train_submissions (kind, prompt_id, mode, status, "
        "duration_s, band, created_at, updated_at) "
        "VALUES ('writing', 'w1', 'practice', 'reviewed', 1800, 6, ?, ?)",
        (_at(9), _at(9)))
    conn.commit()


class CheckTest(unittest.TestCase):
    def test_精听要三个不同句子(self):
        conn = _db()
        for _ in range(188):
            _sentence(conn, 10, 1)
        self.assertFalse(day_plan.check(conn, DAY)["checks"]["listen"])
        _sentence(conn, 10, 2)
        _sentence(conn, 10, 3)
        checks = day_plan.check(conn, DAY)["checks"]
        self.assertTrue(checks["listen"])

    def test_训练或复习任一即可(self):
        conn = _db()
        self.assertFalse(day_plan.check(conn, DAY)["checks"]["output"])
        _writing(conn)
        self.assertTrue(day_plan.check(conn, DAY)["checks"]["output"])

        conn = _db()
        conn.execute("INSERT INTO review_log VALUES (?)", (_at(9),))
        self.assertTrue(day_plan.check(conn, DAY)["checks"]["output"])

    def test_开一场测验也算输出(self):
        conn = _db()
        conn.execute("INSERT INTO events VALUES (?, 'quiz', 'quiz')", (_at(9),))
        self.assertTrue(day_plan.check(conn, DAY)["checks"]["output"])

    def test_三个问题也算输出(self):
        conn = _db()
        for index in range(3):
            conn.execute("INSERT INTO asks VALUES (?)", (_at(9),))
        self.assertTrue(day_plan.check(conn, DAY)["checks"]["output"])

    def test_复盘只看今日报告(self):
        conn = _db()
        self.assertFalse(day_plan.check(conn, DAY)["checks"]["report"])
        conn.execute("INSERT INTO events VALUES (?, 'review', 'report')",
                     (_at(21),))
        self.assertTrue(day_plan.check(conn, DAY)["checks"]["report"])

    def test_三格全完成(self):
        conn = _db()
        for sentence in (1, 2, 3):
            _sentence(conn, 10, sentence)
        _writing(conn)
        conn.execute("INSERT INTO events VALUES (?, 'review', 'report')",
                     (_at(21),))
        state = day_plan.check(conn, DAY)
        self.assertEqual(state["done"], 3)
        self.assertEqual(state["total"], 3)
        self.assertEqual(day_plan.build(conn, DAY)["tier"], "done")


class BuildTest(unittest.TestCase):
    def test_没有数据也有三格可做(self):
        conn = _db()
        plan = day_plan.build(conn, DAY)
        self.assertEqual(len(plan["tasks"]), 3)
        self.assertEqual(plan["done"], 0)
        self.assertEqual(plan["tier"], "none")
        self.assertGreater(plan["budget_minutes"], 0)
        self.assertEqual([item["id"] for item in plan["tasks"]],
                         ["listen", "output", "report"])

    def test_两件算达标第三件是加分(self):
        conn = _db()
        for sentence in (1, 2, 3):
            _sentence(conn, 10, sentence)
        _writing(conn)
        plan = day_plan.build(conn, DAY)
        self.assertEqual(plan["done"], 2)
        self.assertEqual(plan["tier"], "met")

    def test_完成状态与check一致(self):
        conn = _db()
        for sentence in (1, 2, 3):
            _sentence(conn, 10, sentence)
        _writing(conn)
        conn.execute("INSERT INTO events VALUES (?, 'review', 'report')",
                     (_at(21),))
        plan = day_plan.build(conn, DAY)
        self.assertTrue(all(item["done"] for item in plan["tasks"]))
        self.assertEqual(plan["done"], 3)

    def test_有到期卡时第二格是复习(self):
        conn = _db()
        yesterday = (datetime.date.fromisoformat(DAY)
                     - datetime.timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO wrong_items (ts, source, source_id, question) "
            "VALUES (?, 'writing', 's1', '为什么这里用虚拟语气')",
            (f"{yesterday} 09:00:00",))
        conn.commit()
        plan = day_plan.build(conn, DAY)
        self.assertEqual(plan["tasks"][1]["title"], "复习到期卡")

    def test_没有到期卡时推荐写作(self):
        conn = _db()
        plan = day_plan.build(conn, DAY)
        self.assertTrue(plan["tasks"][1]["title"].startswith("写作 · "))

    def test_预算随到期卡数量变化(self):
        conn = _db()
        first = day_plan.build(conn, DAY)["budget_minutes"]
        yesterday = (datetime.date.fromisoformat(DAY)
                     - datetime.timedelta(days=1)).isoformat()
        for index in range(5):
            conn.execute(
                "INSERT INTO wrong_items (ts, source, source_id, question) "
                "VALUES (?, 'writing', ?, '题')",
                (f"{yesterday} 09:00:00", f"s{index}"))
        conn.commit()
        second = day_plan.build(conn, DAY)["budget_minutes"]
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
