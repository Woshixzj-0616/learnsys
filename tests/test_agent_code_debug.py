# -*- coding: utf-8 -*-
"""代码调试闭环：路由提档、强制思考、必须运行、未验证标记、重复调用防抖。"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys.agent import loop, prompts, router, tools
from learnsys.agent.turn import _Turn, _RunState, _handle_tool_call
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult, ToolCall

CODE = """#include<iostream>
using namespace std;
int main() {
  int a;
  cin >> a;
  cout << a;
  return 0;
}
这组输出没过，哪里错了？
"""


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    base = AgentConfig(
        base_url="https://api.deepseek.com/anthropic",
        auth_token="test-token",
        model="deepseek-flash",
        fast_model="deepseek-flash",
        strong_model="deepseek-v4-pro",
        max_tokens=4096,
        thinking=False,
        vision_base_url="", vision_api_key="", vision_model="glm-4v-flash",
        data_root=root, profile_path=root / "学习档案.md",
        speed="balanced", auto_route="shadow",
    )
    return dataclasses.replace(base, **overrides)


class _Provider:
    def __init__(self, calls=None):
        self.calls = calls or []
        self.configs = []

    def stream_messages(self, cfg, system, messages, tool_schemas, *, abort=None,
                        response_sink=None):
        self.configs.append((cfg.model, cfg.thinking, system))
        yield ProviderEvent("done", result=ProviderResult(
            text="结论：先跑一下。", stop_reason="end_turn"))


class RouterCodeDebugTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_debug_recommends_thinking_with_main_model(self):
        decision = router.decide(make_cfg(self.root), mode="explain", message=CODE)
        self.assertEqual(decision.tier, "standard")          # 影子不直接改
        self.assertEqual(decision.recommended["tier"], "deep")
        self.assertEqual(decision.recommended["model"], "deepseek-flash")
        self.assertTrue(decision.recommended["thinking"])
        self.assertIn("代码调试", decision.recommended["reason"])

    def test_on_applies_debug(self):
        decision = router.decide(make_cfg(self.root, auto_route="on"),
                                 mode="explain", message=CODE)
        self.assertTrue(decision.thinking)
        self.assertFalse(decision.concise)

    def test_manual_fast_is_respected(self):
        decision = router.decide(make_cfg(self.root, speed="fast"),
                                 mode="explain", message=CODE)
        self.assertEqual(decision.tier, "fast")
        self.assertFalse(decision.thinking)

    def test_prompt_has_rule(self):
        system = prompts.build_system("explain", code_debug=True)
        self.assertIn("本轮是代码调试", system)
        self.assertIn("run_code", system)
        self.assertIn("save_wrongbook", system)
        self.assertIn("error_type", system)
        self.assertIn("test_cases", system)
        self.assertNotIn("本轮是代码调试", prompts.build_system("explain"))


class LoopCodeDebugTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_shadow_forces_thinking_and_marks_unverified(self):
        provider = _Provider()
        events = list(loop.run(loop.AgentRequest(CODE, mode="explain", surface="ask"),
                               provider=provider, cfg=make_cfg(self.root)))
        # 默认 balanced + shadow：实际模型仍是 flash，但思考被强制打开。
        self.assertEqual(provider.configs[0][0], "deepseek-flash")
        self.assertTrue(provider.configs[0][1])
        self.assertIn("本轮是代码调试", provider.configs[0][2])
        activities = [event.text for event in events if event.kind == "activity"]
        self.assertTrue(any("代码调试" in text for text in activities))
        routes = [event for event in events if event.kind == "route"]
        self.assertEqual(routes[0].data.get("forced"), "code_debug")
        done = [event for event in events if event.kind == "done"][0]
        self.assertTrue(done.data["code_unverified"])
        self.assertTrue(done.data["text"].startswith("（未运行验证"))
        self.assertIn("收进复习", done.data["text"], "代码调试结束要主动提议一次")

    def test_non_debug_has_no_review_proposal(self):
        provider = _Provider()
        events = list(loop.run(
            loop.AgentRequest("什么是二叉树", mode="explain", surface="ask"),
            provider=provider, cfg=make_cfg(self.root)))
        done = [event for event in events if event.kind == "done"][0]
        self.assertNotIn("收进复习", done.data["text"])

    def test_quickbar_does_not_force(self):
        provider = _Provider()
        list(loop.run(loop.AgentRequest(CODE, mode="explain", surface="quickbar"),
                      provider=provider, cfg=make_cfg(self.root)))
        self.assertFalse(provider.configs[0][1])

    def test_quiz_does_not_force(self):
        provider = _Provider()
        list(loop.run(loop.AgentRequest(CODE, mode="quiz", surface="ask"),
                      provider=provider, cfg=make_cfg(self.root)))
        self.assertFalse(provider.configs[0][1])


class ToolLabelAndGuardTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(tools.label_for("run_code"), "运行代码")
        self.assertEqual(tools.label_for("web_search"), "联网搜索")
        self.assertEqual(tools.label_for("unknown_tool"), "unknown_tool")

    def _turn(self, root: pathlib.Path) -> _Turn:
        return _Turn(
            request=loop.AgentRequest("x", mode="explain", surface="ask"),
            provider=object(), cfg_holder=[make_cfg(root)],
            system="", tool_schemas=[], messages=[],
            state=_RunState(),
            ctx=tools.ToolContext(data_root=root, db_path=root / "learning.db"),
            image_paths=[], used_vision=False, code_debug=True)

    def test_code_debug_uses_short_run_timeout(self):
        from learnsys.agent.tools import files
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ctx = tools.ToolContext(data_root=root, db_path=root / "learning.db",
                                    code_debug=True)
            with mock.patch.object(files.sandbox, "run") as runner:
                runner.return_value.render.return_value = "ok"
                files.run_code("python", "print(1)", ctx=ctx)
            self.assertEqual(runner.call_args.kwargs["timeout"], 5.0)

    def test_duplicate_run_code_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            turn = self._turn(root)
            call = ToolCall("t1", "run_code", {"language": "python", "code": "print(1)"})
            results = []
            approve = lambda *args, **kwargs: True
            first = list(_handle_tool_call(turn, call, results, confirm=approve, abort=None))
            second = list(_handle_tool_call(turn, call, results, confirm=approve, abort=None))
            self.assertEqual(first[0].kind, "tool_start")
            self.assertEqual(first[-1].kind, "tool_end")
            self.assertNotEqual(first[-1].data.get("preview"), "重复/超限，已跳过")
            self.assertEqual(second[-1].data.get("preview"), "重复/超限，已跳过")
            self.assertEqual(turn.state.tool_attempts["run_code"], 1)
            self.assertIn("run_code", turn.state.tools_ok)


if __name__ == "__main__":
    unittest.main()
