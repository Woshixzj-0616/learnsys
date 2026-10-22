# -*- coding: utf-8 -*-
"""Golden set：任务文件可解析、判分口径正确（不跑真实模型）。"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "golden_run", ROOT / "tools" / "golden_run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GoldenTest(unittest.TestCase):
    def setUp(self):
        self.golden = _load()

    def test_tasks_file_has_twenty_valid_entries(self):
        tasks = self.golden.load_tasks(ROOT / "docs" / "golden" / "tasks.jsonl")
        self.assertGreaterEqual(len(tasks), 20)
        ids = [task["id"] for task in tasks]
        self.assertEqual(len(ids), len(set(ids)), "任务 id 重复")
        for task in tasks:
            self.assertTrue(task.get("prompt"))
            self.assertTrue(task.get("must_all") or task.get("must_any")
                            or task.get("manual"))

    def test_judge_passes_when_all_keywords_present(self):
        task = {"must_all": ["SYN", "ACK"]}
        self.assertEqual(self.golden.judge(task, "先发 SYN，再回 ACK"), [])

    def test_judge_reports_missing_keyword(self):
        task = {"must_all": ["SYN", "ACK"]}
        issues = self.golden.judge(task, "先发 SYN")
        self.assertTrue(issues)
        self.assertIn("ACK", issues[0])

    def test_judge_any_and_forbidden(self):
        task = {"must_any": ["狐狸", "狗"], "must_not": ["抱歉"]}
        self.assertTrue(self.golden.judge(task, "抱歉，我不知道"))
        self.assertEqual(self.golden.judge(task, "那只狐狸跳了过去"), [])

    def test_p95_is_zero_for_empty(self):
        self.assertEqual(self.golden._p95([]), 0)
        self.assertEqual(self.golden._p95([10, 20, 30]), 30)


if __name__ == "__main__":
    unittest.main()
