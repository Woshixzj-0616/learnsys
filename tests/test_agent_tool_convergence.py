# -*- coding: utf-8 -*-
"""P35.2：资料题工具收敛（去重 / 预算提示 / 到上限无工具收口）。"""
from __future__ import annotations

import copy
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent import loop
from learnsys.agent.turn import AgentRequest
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import (
    ProviderEvent,
    ProviderResult,
    ToolCall,
)


def _cfg(root: pathlib.Path) -> AgentConfig:
    return AgentConfig(
        base_url="http://127.0.0.1:9/v1", auth_token="test",
        model="test-model", fast_model="test-fast", max_tokens=1024,
        thinking=False, vision_base_url="", vision_api_key="", vision_model="",
        data_root=root, profile_path=root / "学习档案.md")


class ScriptedProvider:
    """按脚本返回 tool_use；脚本用完后返回最终正文。记录每次请求。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        index = len(self.calls)
        self.calls.append({"tools": tools, "messages": copy.deepcopy(messages)})
        if index < len(self.script):
            name, args = self.script[index]
            call = ToolCall(f"t{index}", name, args)
            yield ProviderEvent("done", result=ProviderResult(
                tool_calls=[call],
                content_blocks=[{"type": "tool_use", "id": call.id,
                                 "name": name, "input": args}],
                stop_reason="tool_use"))
            return
        yield ProviderEvent("done", result=ProviderResult(
            text="根据已有资料回答：TCP 连接建立。", stop_reason="end_turn"))


def _has_hint(messages) -> bool:
    for message in messages:
        contents = message.get("content")
        if not isinstance(contents, list):
            continue
        for block in contents:
            if block.get("type") == "text" and "工具预算" in block.get("text", ""):
                return True
    return False


class ToolConvergenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        store.connect(self.root / "learning.db").close()
        self.cfg = _cfg(self.root)

    def _run(self, provider, max_steps=8):
        request = AgentRequest(
            message="课件里 TCP 三次握手是怎么讲的",
            mode="quick", surface="ask", profile="assistant",
            use_tools=True)
        events = list(loop.run(request, cfg=self.cfg, provider=provider,
                               max_steps=max_steps))
        return events, provider

    def test_identical_readonly_call_is_skipped(self):
        provider = ScriptedProvider([
            ("search_materials", {"query": "TCP 三次握手"}),
            ("search_materials", {"query": "TCP 三次握手"}),
        ])
        executed = []

        def fake_execute(name, args, ctx):
            executed.append((name, dict(args)))
            return "命中：资料 171 第 220 页", "搜资料", True

        with mock.patch("learnsys.agent.turn.tools.execute",
                        side_effect=fake_execute):
            events, _provider = self._run(provider)
        self.assertEqual(len(executed), 1, "同名同参第二次不应真的执行")
        self.assertFalse(any(event.kind == "error" for event in events))
        skipped = [event for event in events if event.kind == "tool_end"
                   and (event.data or {}).get("preview") == "重复/超限，已跳过"]
        self.assertEqual(len(skipped), 1)
        # 第三次模型请求（跳过之后）里应能看到「完全相同」的 tool_result。
        third_messages = provider.calls[2]["messages"]
        self.assertIn("完全相同", str(third_messages))

    def test_budget_hint_is_attached_on_third_call(self):
        provider = ScriptedProvider([
            ("search_materials", {"query": "a"}),
            ("search_materials", {"query": "b"}),
            ("search_materials", {"query": "c"}),
        ])
        with mock.patch("learnsys.agent.turn.tools.execute",
                        side_effect=lambda *args: ("命中", "搜资料", True)):
            events, _provider = self._run(provider)
        self.assertFalse(any(event.kind == "error" for event in events))
        self.assertTrue(_has_hint(provider.calls[3]["messages"]),
                        "第 3 次工具调用后的请求要带工具预算提示")

    def test_max_steps_finishes_without_tools_for_assistant(self):
        provider = ScriptedProvider([
            ("search_materials", {"query": "TCP"}),
        ])
        with mock.patch("learnsys.agent.turn.tools.execute",
                        side_effect=lambda *args: ("命中", "搜资料", True)):
            events, _provider = self._run(provider, max_steps=1)
        errors = [event for event in events if event.kind == "error"]
        self.assertEqual(errors, [], "助手 profile 不应再报「工具调用次数太多」")
        done = [event for event in events if event.kind == "done"][-1]
        self.assertIn("TCP 连接建立", done.data.get("text", ""))
        self.assertIsNone(provider.calls[1]["tools"], "收口轮不能再给工具")
        self.assertTrue(_has_hint(provider.calls[1]["messages"]))

    def test_legacy_profile_still_reports_tool_limit(self):
        provider = ScriptedProvider([
            ("today_summary", {}),
        ])
        request = AgentRequest(message="今天学了什么", surface="ask", use_tools=True)
        events = list(loop.run(request, cfg=self.cfg, provider=provider,
                               max_steps=1))
        errors = [event for event in events if event.kind == "error"]
        self.assertTrue(errors)
        self.assertIn("工具调用次数太多", errors[-1].text)


if __name__ == "__main__":
    unittest.main()
