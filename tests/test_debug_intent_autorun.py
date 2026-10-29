# -*- coding: utf-8 -*-
"""代码调试判据放宽 + 明确要求运行时不再弹 run_code 确认。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.agent import debug_intent, loop, sandbox
from learnsys.agent.events import AgentEvent
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult, ToolCall
from learnsys.server.app import create_app


def make_cfg(root: pathlib.Path) -> AgentConfig:
    return AgentConfig(
        base_url="http://127.0.0.1:9/v1",
        auth_token="test-token",
        model="test-model",
        fast_model="test-fast",
        max_tokens=1024,
        thinking=False,
        vision_base_url="",
        vision_api_key="",
        vision_model="glm-4v-flash",
        data_root=root,
        profile_path=root / "学习档案.md",
    )


def tool_use(text: str, name: str, args: dict) -> ProviderResult:
    return ProviderResult(
        text=text,
        tool_calls=[ToolCall("call-0", name, args)],
        content_blocks=([{"type": "text", "text": text}] if text else [])
        + [{"type": "tool_use", "id": "call-0", "name": name, "input": args}],
        stop_reason="tool_use",
    )


class ScriptProvider:
    def __init__(self, *results: ProviderResult):
        self.results = list(results)

    def stream_messages(self, cfg, system, messages, tools, *, abort=None,
                        response_sink=None):
        result = self.results.pop(0) if self.results else ProviderResult(
            text="", stop_reason="end_turn")
        if result.text:
            yield ProviderEvent("text", result.text)
        yield ProviderEvent("done", result=result)


class DebugIntentTest(unittest.TestCase):
    def test_long_code_with_problem_statement_is_debug(self):
        message = ("1. (程序题, 17分)\n题目：表达式求值\n输入格式：每组一行\n"
                   "输出格式：保留两位小数\n样例：2+2=\n") + "\n".join(
                       ["#include<iostream>"] * 16)
        result = debug_intent.detect(message)
        self.assertTrue(result["code_debug"])
        self.assertTrue(result["has_code"])

    def test_short_snippet_is_not_debug(self):
        result = debug_intent.detect("这段代码哪里错？\n#include<iostream>\nint main(){}")
        self.assertFalse(result["code_debug"])

    def test_run_request_without_code_is_run_requested(self):
        result = debug_intent.detect("你跑几个具体用例，假设输入都合法")
        self.assertTrue(result["run_requested"])
        self.assertFalse(result["code_debug"])

    def test_plain_question_is_not_run_requested(self):
        result = debug_intent.detect("解释一下进程和线程的区别")
        self.assertFalse(result["run_requested"])


class LanguageGuessTest(unittest.TestCase):
    def test_guess_language(self):
        self.assertEqual(sandbox.guess_language("#include<iostream>\nint main(){}"), "cpp")
        self.assertEqual(sandbox.guess_language("#include<stdio.h>\nint main(){}"), "c")
        self.assertEqual(sandbox.guess_language("def main():\n    print(1)"), "python")
        self.assertEqual(sandbox.guess_language("随便一段话"), "")

    def test_empty_language_is_inferred_and_runs(self):
        result = sandbox.run("", "print(6 * 7)")
        self.assertTrue(result.ok, result.note)
        self.assertEqual(result.language, "python")
        self.assertIn("42", result.stdout)


class AutoRunCodeTest(unittest.TestCase):
    def test_auto_run_code_skips_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            fake = ScriptProvider(
                tool_use("跑一下。", "run_code",
                         {"language": "python", "code": "print(6 * 7)"}),
                ProviderResult(text="输出是 42。", stop_reason="end_turn"),
            )
            events = list(loop.run(
                loop.AgentRequest("跑几个用例验证", auto_run_code=True),
                provider=fake, cfg=cfg,
                confirm=lambda *_: self.fail("明确要求运行时不该弹确认")))
            kinds = [event.kind for event in events]
            self.assertNotIn("confirm", kinds)
            tool_end = [event for event in events if event.kind == "tool_end"][0]
            self.assertTrue(tool_end.data["ok"])
            self.assertIn("运行成功", tool_end.data.get("preview") or "")


class ChatAutoRunFlagTest(unittest.TestCase):
    """问一问路由要把「用户明确要求跑」翻译成 AgentRequest.auto_run_code。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        self.root_patch = mock.patch.object(
            app_config, "DATA_ROOT", pathlib.Path(self.tmp.name))
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        store.connect(self.db_path).close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token="t"))

    def _auto_flag(self, message: str) -> bool:
        seen = []

        def fake_run(request, cfg=None, abort=None, **_kwargs):
            seen.append(request)
            yield AgentEvent("done", data={"text": "答", "stop_reason": "end_turn"})

        with mock.patch("learnsys.server.routes_agent.agent.run", fake_run):
            res = self.client.post("/api/agent/chat",
                                   headers={"X-Learnsys-Token": "t"},
                                   json={"message": message})
        self.assertEqual(res.status_code, 200)
        return bool(seen[0].auto_run_code)

    def test_explicit_run_request_auto_runs(self):
        self.assertTrue(self._auto_flag("你跑几个具体用例，假设输入都合法"))

    def test_plain_question_does_not_auto_run(self):
        self.assertFalse(self._auto_flag("解释一下进程和线程的区别"))

    def test_long_code_with_problem_statement_auto_runs(self):
        message = ("题目：表达式求值\n输入格式：每组一行\n输出格式：保留两位小数\n"
                   "样例：2+2=\n") + "\n".join(["#include<iostream>"] * 16)
        self.assertTrue(self._auto_flag(message))


if __name__ == "__main__":
    unittest.main()
