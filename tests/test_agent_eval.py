"""Agent 评测脚本：题库格式、只读边界、判分规则、空库不炸。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent.events import AgentEvent
from tools import agent_eval_core as core


class SuiteTest(unittest.TestCase):
    def setUp(self):
        self.suite = core.load_suite(core.SUITE_PATH)

    def test_ids_unique_and_questions_present(self):
        ids = [case["id"] for case in self.suite["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        for case in self.suite["cases"]:
            self.assertTrue(case.get("question"), case["id"])

    def test_offline_only_uses_read_only_tools(self):
        for case in self.suite["cases"]:
            for call in (case.get("offline") or {}).get("tools") or []:
                self.assertIn(call["name"], core.READ_ONLY_TOOLS,
                              f"{case['id']} 的离线段用了写工具 {call['name']}")

    def test_every_live_case_has_expectation(self):
        for case in self.suite["cases"]:
            spec = case.get("live")
            if not spec:
                continue
            self.assertTrue(
                spec.get("must_use_all") or spec.get("must_use_any")
                or spec.get("answer_contains_any"),
                f"{case['id']} 没有任何判分规则")


class GradeLiveTest(unittest.TestCase):
    def _case(self, **live):
        return {"id": "x", "live": live}

    def _obs(self, **over):
        data = {"tools": ["due_reviews"], "errors": [], "check_issues": [],
                "answer": "今天有 3 张到期卡片，建议先复习错题 #12。",
                "steps": 2, "tool_calls": 1}
        data.update(over)
        return data

    def test_pass(self):
        ok, reasons = core.grade_live(
            self._case(must_use_all=["due_reviews"], max_steps=3,
                       max_tool_calls=3), self._obs())
        self.assertTrue(ok, reasons)

    def test_missing_tool(self):
        ok, reasons = core.grade_live(
            self._case(must_use_all=["due_reviews", "recent_wrong_items"]),
            self._obs())
        self.assertFalse(ok)
        self.assertIn("recent_wrong_items", reasons[0])

    def test_step_budget(self):
        ok, reasons = core.grade_live(
            self._case(max_steps=1), self._obs(steps=2))
        self.assertFalse(ok)
        self.assertIn("超过上限", reasons[0])

    def test_check_issues_only_when_required(self):
        case = self._case(must_use_any=["due_reviews"])
        ok, _ = core.grade_live(case, self._obs(check_issues=["引用对不上"]))
        self.assertTrue(ok)
        ok, reasons = core.grade_live(
            self._case(must_use_any=["due_reviews"], require_check_ok=True),
            self._obs(check_issues=["引用对不上"]))
        self.assertFalse(ok)
        self.assertIn("引用自检", reasons[0])

    def test_forbidden_answer_text(self):
        ok, reasons = core.grade_live(
            self._case(answer_not_contains=["已记住"]),
            self._obs(answer="已记住这条偏好。"))
        self.assertFalse(ok)
        self.assertIn("不该有", reasons[0])

    def test_error_event_fails(self):
        ok, reasons = core.grade_live(
            self._case(must_use_any=["due_reviews"]),
            self._obs(errors=["模型没有返回结果"]))
        self.assertFalse(ok)
        self.assertIn("运行报错", reasons[0])


class CollectLiveTest(unittest.TestCase):
    """在线段的事件解析用假 run 验证，不真的调模型。"""

    def test_parses_events_and_denies_writes(self):
        confirmed = []

        def fake_run(request, cfg=None, abort=None, confirm=None,
                     response_sink=None):
            yield AgentEvent("tool_start", data={"name": "save_memory"})
            if confirm is not None:
                approved = confirm("id", "save_memory", {"content": "x"})
                confirmed.append(approved)
            yield AgentEvent("check", data={"issues": ["引用对不上"]})
            yield AgentEvent("done", data={
                "text": "这条偏好没有执行，需要你确认。",
                "steps": 2, "tool_calls": 1, "cost": 0.001})

        case = {"id": "guard", "question": "以后用中文", "mode": "explain",
                "surface": "ask"}
        with mock.patch("learnsys.agent.loop.run", fake_run):
            obs = core.collect_live(case, cfg=None)
        self.assertEqual(obs["tools"], ["save_memory"])
        self.assertEqual(confirmed, [False])
        self.assertEqual(obs["check_issues"], ["引用对不上"])
        self.assertEqual(obs["steps"], 2)
        self.assertIn("没有执行", obs["answer"])


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        store.connect(self.root / "learning.db").close()

    def test_empty_db_does_not_raise(self):
        case = {"id": "due", "domain": "复习队列", "mode": "explain",
                "offline": {"tools": [{"name": "due_reviews", "args": {}}],
                            "min_chars": 5}}
        result = core.run_offline_case(case, self.root)
        self.assertIn(result["status"], {"通过", "空数据", "失败"})
        self.assertFalse(any("抛异常" in item for item in result["details"]))

    def test_write_tool_is_refused(self):
        case = {"id": "bad", "offline": {
            "tools": [{"name": "save_memory", "args": {"content": "x"}}]}}
        result = core.run_offline_case(case, self.root)
        self.assertEqual(result["status"], "失败")
        self.assertIn("不是只读工具", result["details"][0])

    def test_require_data_turns_empty_into_failure(self):
        case = {"id": "need", "offline": {
            "tools": [{"name": "due_reviews", "args": {}}],
            "min_chars": 5, "require_data": True}}
        result = core.run_offline_case(case, self.root)
        self.assertEqual(result["status"], "失败")


class BaselineTest(unittest.TestCase):
    def test_compare_reports_regression(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / "baseline.json"
        path.write_text(json.dumps({
            "version": 1,
            "live": {"a": {"pass": True}, "b": {"pass": False}},
        }), encoding="utf-8")
        old = core.BASELINE_PATH
        core.BASELINE_PATH = path
        try:
            lines = core.compare("live", [
                {"id": "a", "pass": False},
                {"id": "b", "pass": True},
            ])
        finally:
            core.BASELINE_PATH = old
        text = "\n".join(lines)
        self.assertIn("退化：a", text)
        self.assertIn("改进：b", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
