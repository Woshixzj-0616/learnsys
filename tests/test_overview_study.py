# -*- coding: utf-8 -*-
"""学习记录时长口径（2026-10-28 任务制改版）。

锁四件事：
① 实测只认有起止的证据：专注 / 转写 / 训练提交秒数；
② 估算有上限：断点按「不同句子数」折算，同一句按 188 次也只算一次；
③ 构成（breakdown）相加等于总分钟，跨午夜的区间裁到当天；
④ 断点、问答只进 activity，不再按「一条 2 分钟」虚增时长。
"""
from __future__ import annotations

import datetime
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys.services.study_time import (  # noqa: E402
    clip, merge_minutes, recorded, study)

DAY = "2026-10-28"

SCHEMA = """
CREATE TABLE sessions (started_at TEXT, ended_at TEXT);
CREATE TABLE transcripts (ts_start TEXT, ts_end TEXT);
CREATE TABLE asks (ts TEXT);
CREATE TABLE cet6_events (
    ts TEXT, paper_id TEXT, paper_title TEXT, section TEXT, item TEXT,
    sentence INTEGER);
CREATE TABLE events (ts TEXT, module TEXT, kind TEXT);
CREATE TABLE review_log (ts TEXT);
CREATE TABLE train_submissions (
    created_at TEXT, updated_at TEXT, duration_s INTEGER, status TEXT);
CREATE TABLE quiz_attempts (ts TEXT, day TEXT);
"""


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def _at(hour: int, minute: int, second: int = 0) -> str:
    return datetime.datetime(2026, 10, 28, hour, minute, second).strftime(
        "%Y-%m-%d %H:%M:%S")


def _cet6(conn, hour: int, sentence: int, item: str = "Recording 1") -> None:
    conn.execute(
        "INSERT INTO cet6_events VALUES (?, '卷一', '测试卷', 'Section C', ?, ?)",
        (_at(hour, 0), item, sentence))


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


class RecordedMinutesTest(unittest.TestCase):
    def test_专注按真实起止计实测(self):
        conn = _db()
        conn.execute("INSERT INTO sessions VALUES (?, ?)", (_at(9, 0), _at(9, 30)))
        data = recorded(conn, DAY)
        self.assertEqual(data["measured"], 30.0)
        self.assertEqual(data["estimated"], 0.0)
        self.assertEqual(data["minutes"], 30.0)
        self.assertEqual(data["breakdown"], {"focus": 30.0})

    def test_转写按真实起止计实测(self):
        conn = _db()
        conn.execute("INSERT INTO transcripts VALUES (?, ?)",
                     (_at(8, 0), _at(8, 20)))
        data = recorded(conn, DAY)
        self.assertEqual(data["measured"], 20.0)
        self.assertEqual(data["breakdown"]["transcript"], 20.0)

    def test_训练提交按秒数计实测(self):
        conn = _db()
        conn.execute(
            "INSERT INTO train_submissions VALUES (?, ?, 1800, 'reviewed')",
            (_at(9, 0), _at(9, 30)))
        data = recorded(conn, DAY)
        self.assertEqual(data["measured"], 30.0)
        self.assertEqual(data["breakdown"]["train"], 30.0)

    def test_训练落在专注区间内不重复计(self):
        conn = _db()
        conn.execute("INSERT INTO sessions VALUES (?, ?)", (_at(9, 0), _at(9, 30)))
        conn.execute(
            "INSERT INTO train_submissions VALUES (?, ?, 1800, 'reviewed')",
            (_at(9, 5), _at(9, 35)))
        data = recorded(conn, DAY)
        self.assertEqual(data["measured"], 30.0)
        self.assertNotIn("train", data["breakdown"])

    def test_问答是估算且有上限(self):
        conn = _db()
        for index in range(3):
            conn.execute("INSERT INTO asks VALUES (?)", (_at(9, index),))
        data = recorded(conn, DAY)
        self.assertEqual(data["estimated"], 6.0)
        self.assertEqual(data["breakdown"]["asks"], 6.0)
        self.assertEqual(data["activity"]["asks"], 3)

        conn = _db()
        for index in range(50):
            conn.execute("INSERT INTO asks VALUES (?)", (_at(9, index % 60),))
        self.assertEqual(recorded(conn, DAY)["breakdown"]["asks"], 20.0)

    def test_断点按不同句子折算而不是按键次数(self):
        conn = _db()
        for _ in range(188):
            _cet6(conn, 10, 1)                     # 同一句按 188 次
        data = recorded(conn, DAY)
        self.assertEqual(data["breakdown"]["cet6"], 2.0)
        self.assertEqual(data["activity"]["breakpoints"], 188)
        self.assertEqual(data["activity"]["sentences"], 1)

    def test_断点单段录音封顶三十分钟(self):
        conn = _db()
        for sentence in range(1, 21):              # 20 句 × 2 = 40，封顶 30
            _cet6(conn, 10, sentence)
        self.assertEqual(recorded(conn, DAY)["breakdown"]["cet6"], 30.0)

    def test_复习按张数估算(self):
        conn = _db()
        for index in range(10):
            conn.execute("INSERT INTO review_log VALUES (?)",
                         (_at(9, index),))
        data = recorded(conn, DAY)
        self.assertEqual(data["breakdown"]["review"], 5.0)
        self.assertEqual(data["activity"]["reviews"], 10)

    def test_构成相加等于总数(self):
        conn = _db()
        conn.execute("INSERT INTO sessions VALUES (?, ?)", (_at(9, 0), _at(9, 30)))
        conn.execute("INSERT INTO transcripts VALUES (?, ?)",
                     (_at(9, 5), _at(9, 15)))
        conn.execute("INSERT INTO asks VALUES (?)", (_at(9, 40),))
        _cet6(conn, 10, 1)
        conn.execute("INSERT INTO events VALUES (?, 'review', 'report')",
                     (_at(10, 30),))
        data = recorded(conn, DAY)
        self.assertAlmostEqual(sum(data["breakdown"].values()), data["minutes"],
                               places=1)

    def test_只统计当天(self):
        conn = _db()
        conn.execute("INSERT INTO sessions VALUES (?, ?)",
                     ("2026-10-27 23:50:00", "2026-10-28 00:10:00"))
        self.assertEqual(recorded(conn, DAY)["measured"], 10.0)

    def test_未结束的专注算到此刻(self):
        conn = _db()
        started = (datetime.datetime.now() - datetime.timedelta(minutes=5)
                   ).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO sessions VALUES (?, '')", (started,))
        data = recorded(conn, datetime.date.today().isoformat())
        self.assertGreaterEqual(data["measured"], 4.0)
        self.assertLessEqual(data["measured"], 6.0)

    def test_旧study接口仍返回二值(self):
        conn = _db()
        conn.execute("INSERT INTO sessions VALUES (?, ?)", (_at(9, 0), _at(9, 30)))
        minutes, breakdown = study(conn, DAY)
        self.assertEqual(minutes, 30.0)
        self.assertEqual(breakdown["focus"], 30.0)


if __name__ == "__main__":
    unittest.main()
