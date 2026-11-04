# -*- coding: utf-8 -*-
"""双写退休报告：连续天数、未知日、文件模式、次要差异与 13 天事实。"""
from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from tools import cet6_dualwrite_report as report_tool


def day_range(start: str, end: str) -> list[str]:
    a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    out = []
    while a <= b:
        out.append(a.isoformat())
        a += dt.timedelta(days=1)
    return out


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)

    def add(self, day: str, *, paper="p1", mode="http", status="ok",
            diff_fields=0, minor_fields=0, missing_db=0, orphan_db=0,
            orphan_blocking=0, invalid=0, post_ok=1, compared=10):
        store.add_cet6_dualwrite_run(
            self.conn, ts=f"{day} 08:00:00", day=day, paper_id=paper,
            mode=mode, status=status, diff_fields=diff_fields,
            minor_fields=minor_fields, missing_db=missing_db, orphan_db=orphan_db,
            orphan_blocking=orphan_blocking, invalid=invalid, post_ok=post_ok,
            compared=compared)

    def run_report(self, **kw):
        return report_tool.collect(db_path=self.db, start=dt.date(2026, 10, 21),
                                   end=dt.date(2026, 11, 4),
                                   today=dt.date(2026, 11, 4), **kw)

    def run_relaxed(self, *, today="2026-11-04", **kw):
        return report_tool.collect(
            db_path=self.db, start=dt.date(2026, 10, 21),
            end=dt.date(2026, 11, 4), today=dt.date.fromisoformat(today),
            policy="relaxed", **kw)

    def test_thirteen_days_is_not_enough(self):
        for day in day_range("2026-10-23", "2026-11-04"):
            self.add(day)
        data = self.run_report()
        self.assertEqual(data["available_days"], 13)
        self.assertEqual(data["clean_days"], 13)
        self.assertEqual(data["streak"], 13)
        self.assertFalse(data["eligible"])
        self.assertEqual(data["earliest_eligible"], "2026-11-05")
        text = report_tool.render(data)
        self.assertIn("不足 14 天", text)
        self.assertIn("2026-11-05", text)
        self.assertIn("不能按原计划切换", text)

    def test_fourteen_days_is_enough(self):
        for day in day_range("2026-10-22", "2026-11-04"):
            self.add(day)
        data = self.run_report()
        self.assertEqual(data["streak"], 14)
        self.assertTrue(data["eligible"])
        self.assertEqual(data["earliest_eligible"], "2026-11-04")

    def test_dirty_day_breaks_streak(self):
        for day in day_range("2026-10-23", "2026-11-04"):
            self.add(day, diff_fields=1 if day == "2026-10-28" else 0,
                     status="diff" if day == "2026-10-28" else "ok")
        data = self.run_report()
        self.assertEqual(data["streak"], 7)          # 10-29 到 11-04
        self.assertEqual(data["streak_start"], "2026-10-29")
        self.assertEqual(data["earliest_eligible"], "2026-11-11")
        self.assertFalse(data["eligible"])

    def test_missing_day_is_unknown_and_breaks_streak(self):
        for day in day_range("2026-10-23", "2026-11-04"):
            if day != "2026-10-28":
                self.add(day)
        data = self.run_report()
        self.assertEqual(data["unknown_days"], 1)
        self.assertEqual(data["streak_start"], "2026-10-29")
        self.assertFalse(data["eligible"])

    def test_file_mode_is_not_http_evidence(self):
        for day in day_range("2026-10-23", "2026-11-04"):
            self.add(day, mode="file" if day == "2026-10-30" else "http")
        data = self.run_report()
        self.assertEqual(data["streak_start"], "2026-10-31")
        self.assertFalse(data["eligible"])

    def test_minor_plays_allowed_by_default_but_not_strict(self):
        for day in day_range("2026-10-22", "2026-11-04"):
            self.add(day, minor_fields=1,
                     status="ok_minor" if day == "2026-10-25" else "ok")
        self.assertTrue(self.run_report()["eligible"])
        self.assertFalse(self.run_report(strict_plays=True)["eligible"])

    def test_no_runs_is_not_an_error(self):
        data = self.run_report()
        self.assertIsNone(data["first_evidence"])
        self.assertEqual(data["available_days"], 0)
        self.assertFalse(data["eligible"])

    def test_blocked_or_failed_post_is_dirty(self):
        for day in day_range("2026-10-23", "2026-11-04"):
            self.add(day, status="blocked_empty" if day == "2026-10-26" else "ok",
                     compared=0 if day == "2026-10-26" else 10)
        data = self.run_report()
        self.assertEqual(data["streak_start"], "2026-10-27")
        self.assertFalse(data["eligible"])

    def test_relaxed_thresholds_met_but_before_judge_date(self):
        for day in day_range("2026-10-31", "2026-11-04"):
            self.add(day)
        data = self.run_relaxed()
        self.assertTrue(data["thresholds_met"])
        self.assertFalse(data["due"])
        self.assertFalse(data["eligible"])
        self.assertEqual(data["earliest_eligible"], "2026-11-09")
        text = report_tool.render(data)
        self.assertIn("门槛已满足", text)
        self.assertIn("还差 5 天", text)
        self.assertNotIn("不足 14 天", text)

    def test_relaxed_eligible_on_judge_date(self):
        for day in day_range("2026-10-31", "2026-11-04"):
            self.add(day)
        data = self.run_relaxed(today="2026-11-09")
        self.assertTrue(data["thresholds_met"])
        self.assertTrue(data["due"])
        self.assertTrue(data["eligible"])
        self.assertIn("可以按计划退休", report_tool.render(data))

    def test_relaxed_thresholds_not_met_on_judge_date(self):
        for day in ("2026-11-03", "2026-11-04"):
            self.add(day)
        data = self.run_relaxed(today="2026-11-09")
        self.assertFalse(data["thresholds_met"])
        self.assertFalse(data["eligible"])
        text = report_tool.render(data)
        self.assertIn("判定日已到", text)
        self.assertIn("不能退休", text)

    def test_cli_end_defaults_to_today(self):
        fake = {"eligible": False}
        with mock.patch.object(report_tool, "collect", return_value=fake) as collect:
            code = report_tool.main(["--db", str(self.db), "--today", "2026-11-04", "--json"])
        self.assertEqual(code, 2)
        kwargs = collect.call_args.kwargs
        self.assertEqual(kwargs["end"], dt.date(2026, 11, 4))
        self.assertEqual(kwargs["policy"], "relaxed")


if __name__ == "__main__":
    unittest.main()
