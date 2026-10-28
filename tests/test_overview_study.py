# -*- coding: utf-8 -*-
"""有效学习分钟口径（2026-10-28）。

锁三件事：
① 专注 / 转写 / 事件按分钟并集去重，重叠部分不重复计；
② 没有时长的行为（问答 / 六级 / 训练）按 2 分钟一段，相邻事件只算一次；
③ 构成（breakdown）相加等于总分钟，跨午夜的区间裁到当天。
"""
from __future__ import annotations

import datetime
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys.services.study_time import (  # noqa: E402
    clip, merge_minutes, study)

DAY = "2026-10-28"

SCHEMA = """
CREATE TABLE sessions (started_at TEXT, ended_at TEXT);
CREATE TABLE transcripts (ts_start TEXT, ts_end TEXT);
CREATE TABLE asks (ts TEXT);
CREATE TABLE cet6_events (ts TEXT);
CREATE TABLE events (ts TEXT, module TEXT);
"""


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def _at(hour: int, minute: int, second: int = 0) -> str:
    return datetime.datetime(2026, 10, 28, hour, minute, second).strftime(
        "%Y-%m-%d %H:%M:%S")


class MergeMinutesTest(unittest.TestCase):
    def test_重叠区间只算一次(self):
        lo = datetime.datetime(2026, 10, 28, 9, 0)
        spans = [(lo, lo + datetime.timedelta(minutes=10)),
                 (lo + datetime.timedelta(minutes=5),
                  lo + datetime.timedelta(minutes=15))]
        self.assertEqual(merge_minutes(spans), 15.0)

    def test_空区间为零(self):
        self.assertEqual(merge_minutes([]), 0.0)

    def test_裁剪到当天(self):
        lo = datetime.datetime(2026, 10, 27, 23, 50)
        spans = [(lo, lo + datetime.timedelta(minutes=20))]
        clipped = clip(spans, DAY)
        self.assertEqual(len(clipped), 1)
        self.assertEqual(merge_minutes(clipped), 10.0)


class StudyMinutesTest(unittest.TestCase):
    def test_专注与事件重叠不重复(self):
        conn = _db()
        conn.execute("INSERT INTO sessions VALUES (?, ?)", (_at(9, 0), _at(9, 30)))
        conn.execute("INSERT INTO asks VALUES (?)", (_at(9, 10),))
        conn.execute("INSERT INTO asks VALUES (?)", (_at(9, 20),))
        total, breakdown = study(conn, DAY)
        self.assertEqual(total, 30.0)
        self.assertEqual(breakdown["focus"], 30.0)
        self.assertNotIn("activity", breakdown)

    def test_没有录像时事件按两分钟一段(self):
        conn = _db()
        conn.execute("INSERT INTO asks VALUES (?)", (_at(9, 0),))
        conn.execute("INSERT INTO asks VALUES (?)", (_at(9, 1),))   # 与上一条重叠
        total, breakdown = study(conn, DAY)
        self.assertEqual(total, 3.0)          # [9:00, 9:03]
        self.assertEqual(breakdown["activity"], 3.0)

        conn.execute("INSERT INTO asks VALUES (?)", (_at(9, 10),))  # 新的一段
        total, _ = study(conn, DAY)
        self.assertEqual(total, 5.0)

    def test_转写区间按真实时长(self):
        conn = _db()
        conn.execute("INSERT INTO transcripts VALUES (?, ?)", (_at(8, 0), _at(8, 20)))
        total, breakdown = study(conn, DAY)
        self.assertEqual(total, 20.0)
        self.assertEqual(breakdown["transcript"], 20.0)

    def test_构成相加等于总数(self):
        conn = _db()
        conn.execute("INSERT INTO sessions VALUES (?, ?)", (_at(9, 0), _at(9, 30)))
        conn.execute("INSERT INTO transcripts VALUES (?, ?)", (_at(9, 5), _at(9, 15)))
        conn.execute("INSERT INTO asks VALUES (?)", (_at(9, 40),))
        conn.execute("INSERT INTO cet6_events VALUES (?)", (_at(10, 0),))
        conn.execute("INSERT INTO events VALUES (?, 'train')", (_at(10, 30),))
        total, breakdown = study(conn, DAY)
        self.assertEqual(total, 36.0)          # 30 + 2 + 2 + 2
        self.assertAlmostEqual(sum(breakdown.values()), total, places=1)

    def test_只统计当天(self):
        conn = _db()
        conn.execute("INSERT INTO sessions VALUES (?, ?)",
                     ("2026-10-27 23:50:00", "2026-10-28 00:10:00"))
        total, _ = study(conn, DAY)
        self.assertEqual(total, 10.0)          # 只算 00:00–00:10

    def test_未结束的专注算到此刻(self):
        conn = _db()
        started = (datetime.datetime.now() - datetime.timedelta(minutes=5)
                   ).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO sessions VALUES (?, '')", (started,))
        total, _ = study(conn, datetime.date.today().isoformat())
        self.assertGreaterEqual(total, 4.0)
        self.assertLessEqual(total, 6.0)


if __name__ == "__main__":
    unittest.main()
