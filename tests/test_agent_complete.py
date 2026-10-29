# -*- coding: utf-8 -*-
"""单轮模型接口：服务只依赖 `agent.complete()`，不再各自解析事件流。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys import agent as agent_pkg  # noqa: E402
from learnsys.agent.events import AgentEvent  # noqa: E402
from learnsys.agent.single_turn import complete  # noqa: E402


class AgentCompleteTest(unittest.TestCase):
    def test_done_event_returns_text_and_usage(self):
        usage = {"input_tokens": 12, "output_tokens": 3}

        def fake_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("done", data={"text": "答案", "usage": usage})

        with mock.patch.object(agent_pkg, "run", fake_run):
            text, error, got = complete("问", system_override="系统", mode="quick")
        self.assertEqual((text, error, got), ("答案", "", usage))

    def test_error_event_returns_error(self):
        def fake_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("error", text="模型挂了")

        with mock.patch.object(agent_pkg, "run", fake_run):
            text, error, usage = complete("问")
        self.assertEqual(text, "")
        self.assertEqual(error, "模型挂了")
        self.assertEqual(usage, {})

    def test_exception_becomes_error_string(self):
        def fake_run(request, cfg=None, abort=None, **_kwargs):
            raise RuntimeError("连接断了")

        with mock.patch.object(agent_pkg, "run", fake_run):
            text, error, _usage = complete("问")
        self.assertEqual(text, "")
        self.assertEqual(error, "连接断了")

    def test_request_options_are_forwarded(self):
        seen = {}

        def fake_run(request, cfg=None, abort=None, **_kwargs):
            seen.update({"prompt": request.message,
                         "system": request.system_override,
                         "tools": request.use_tools,
                         "mode": request.mode})
            yield AgentEvent("done", data={"text": "ok"})

        with mock.patch.object(agent_pkg, "run", fake_run):
            complete("问", system_override="系统", mode="briefing")
        self.assertEqual(seen, {"prompt": "问", "system": "系统",
                                "tools": False, "mode": "briefing"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
