# -*- coding: utf-8 -*-
"""快捷栏「深入讲」与逐轮流水：请求标记、深入口提示、agent_runs 只写一次。"""
from __future__ import annotations

import unittest
from unittest import mock

from PySide6 import QtCore, QtWidgets

from learnsys.agent.events import AgentEvent
from learnsys.ask.quickbar import bar, workers


def _cfg(model="deepseek-flash"):
    return mock.Mock(model=model)


def _run_with(events, deep=False):
    """在测试线程里直接跑 worker.run，返回 (worker, 捕获的请求, 写入的流水列表)。"""
    worker = workers._AskWorker("", "哈希表怎么做？", [], None, mode="explain")
    worker._deep = deep
    requests = []
    runs = []
    done = []
    suggested = []

    def fake_run(request, **kwargs):
        requests.append(request)
        yield from events

    conn = mock.Mock()
    with mock.patch.object(workers, "personal_state", return_value=""), \
            mock.patch.object(workers.agent, "run", fake_run), \
            mock.patch.object(workers, "load_config", return_value=_cfg()), \
            mock.patch.object(workers.store, "connect", return_value=conn), \
            mock.patch.object(workers.store, "add_agent_run",
                               side_effect=lambda _conn, **kw: runs.append(kw)):
        worker.done.connect(done.append)
        if hasattr(worker, "deep_suggested"):
            worker.deep_suggested.connect(suggested.append)
        worker.run()
    return worker, requests, runs, done, suggested


def _ok_events(text="答案选 C。"):
    return [
        AgentEvent("text", text=text),
        AgentEvent("done", data={
            "text": text, "usage": {"total_tokens": 10}, "steps": 1,
            "model_calls": 1, "tool_calls": 0, "stop_reason": "end_turn",
            "cost": 0.001, "currency": "CNY", "model": "deepseek-flash",
        }),
    ]


class QuickbarDeepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_deep_flag_reaches_request_and_run(self):
        worker, requests, runs, done, suggested = _run_with(
            _ok_events("深入答案"), deep=True)
        self.assertTrue(requests[0].deep)
        self.assertEqual(done, ["深入答案"])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["model"], "deepseek-flash")
        self.assertIsNotNone(worker._run_info["first_ms"])
        self.assertTrue(worker._run_info["deep"])
        self.assertEqual(suggested, [])      # 已经是深入轮，不再提示

    def test_route_recommendation_offers_deep(self):
        events = [
            AgentEvent("route", data={
                "tier": "standard", "model": "deepseek-flash",
                "recommended": {"tier": "deep", "model": "deepseek-v4-pro"},
            }),
            *_ok_events("普通答案"),
        ]
        _worker, _requests, _runs, done, suggested = _run_with(events)
        self.assertEqual(done, ["普通答案"])
        self.assertIn("complex", suggested)

    def test_self_correction_offers_deep(self):
        _worker, _requests, _runs, _done, suggested = _run_with(
            _ok_events("答案选 C。等一下，答案是 D。"))
        self.assertIn("audit", suggested)

    def test_error_path_writes_exactly_one_run(self):
        events = [AgentEvent("error", text="模型服务不可用")]
        worker, _requests, runs, done, _suggested = _run_with(events)
        self.assertEqual(done, [])
        self.assertEqual(len(runs), 1)
        self.assertIn("模型服务不可用", runs[0]["error"])
        self.assertEqual(worker._run_info["error"], "模型服务不可用")


class QuickbarDeepUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def test_start_deep_reuses_last_turn_as_explain(self):
        self.b._last_turn = {"display_text": "哈希表 ASL", "image_path": "",
                             "context": "", "extra_images": []}
        with mock.patch.object(self.b, "_begin_turn") as begin:
            self.b._start_deep()
        args, kwargs = begin.call_args
        self.assertIn("深入讲", args[1])
        self.assertEqual(kwargs["mode"], "explain")
        self.assertTrue(kwargs["deep"])

    def test_deep_link_only_for_current_turn(self):
        self.b._start_turn("问题")
        self.b._stream_text = "答案"
        self.b._streaming = False
        self.b._current_deep = False
        self.b._deep_hint = "audit"
        self.b._render_answer_view()
        self.assertIn("deep:", self.b.answer.toHtml())
        self.b._turn_seq = 1
        with mock.patch.object(self.b, "_start_deep") as start:
            self.b._on_answer_anchor(QtCore.QUrl("deep:1"))
        self.assertTrue(start.called)

    def test_old_deep_link_is_ignored(self):
        self.b._turn_seq = 3
        with mock.patch.object(self.b, "_start_deep") as start:
            self.b._on_answer_anchor(QtCore.QUrl("deep:2"))
        self.assertFalse(start.called)


if __name__ == "__main__":
    unittest.main()
