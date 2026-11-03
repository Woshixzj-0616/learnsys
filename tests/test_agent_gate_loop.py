# -*- coding: utf-8 -*-
"""取证门控接线：前置提示、补一轮、次轮仍无证据、shadow 不改行为。"""
from __future__ import annotations

import copy
import dataclasses
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys.agent import loop
from learnsys.agent import turn as turn_module
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult, ToolCall

QUESTION = "nginx 最新稳定版是哪个版本？"
BAD = "根因就是 nginx 1.20。"
GOOD = "最可能的最新稳定版是 1.28.1；需要你运行 nginx -v 确认。"


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    base = AgentConfig(
        base_url="http://127.0.0.1:9/v1",
        auth_token="test-token",
        model="deepseek-flash",
        fast_model="deepseek-flash",
        strong_model="",
        max_tokens=1024,
        thinking=False,
        vision_base_url="", vision_api_key="", vision_model="glm-4v-flash",
        data_root=root, profile_path=root / "学习档案.md",
        speed="balanced", auto_route="off", ops_mode="on", ops_gate="on",
    )
    return dataclasses.replace(base, **overrides)


class GateProvider:
    """第一轮凭记忆答，补轮时先搜再答。"""

    def __init__(self):
        self.calls: list[dict] = []

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.calls.append({"messages": copy.deepcopy(messages),
                           "tools": copy.deepcopy(tools), "system": system})
        index = len(self.calls)
        if index == 1:
            yield ProviderEvent("text", BAD)
            yield ProviderEvent("done", result=ProviderResult(
                text=BAD, stop_reason="end_turn"))
            return
        if index == 2:
            call = ToolCall("t1", "web_search", {"query": "nginx server_name"})
            yield ProviderEvent("done", result=ProviderResult(
                tool_calls=[call],
                content_blocks=[{"type": "tool_use", "id": "t1",
                                 "name": "web_search", "input": call.input}],
                stop_reason="tool_use"))
            return
        yield ProviderEvent("text", GOOD)
        yield ProviderEvent("done", result=ProviderResult(
            text=GOOD, stop_reason="end_turn"))


class NeverSearchProvider:
    def __init__(self):
        self.calls: list[dict] = []

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.calls.append({"messages": copy.deepcopy(messages),
                           "tools": copy.deepcopy(tools)})
        yield ProviderEvent("text", BAD)
        yield ProviderEvent("done", result=ProviderResult(
            text=BAD, stop_reason="end_turn"))


class GateLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def run_turn(self, provider, **cfg_overrides):
        events = list(loop.run(
            loop.AgentRequest(QUESTION, mode="explain", surface="ask"),
            provider=provider, cfg=make_cfg(self.root, **cfg_overrides)))
        return events

    def test_gate_round_searches_then_replaces_answer(self):
        provider = GateProvider()
        with mock.patch.object(turn_module.tools, "execute",
                               return_value=("官方文档 https://nginx.org/en/docs/"
                                             "http/server_names.html", "搜到 1 条", True)):
            events = self.run_turn(provider)
        self.assertEqual(len(provider.calls), 3)
        first_user = provider.calls[0]["messages"][-1]["content"][0]["text"]
        self.assertIn("先取证", first_user)
        names = {item["name"] for item in provider.calls[0]["tools"]}
        self.assertNotIn("save_memory", names)
        self.assertNotIn("run_code", names)
        self.assertIn("web_search", names)
        gates = [event for event in events if event.kind == "gate"]
        self.assertEqual(len(gates), 2)              # 前置提示 + 补轮各一条
        self.assertEqual([item.data["round"] for item in gates], [0, 1])
        self.assertTrue(all(item.data["applied"] for item in gates))
        done = [event for event in events if event.kind == "done"][-1]
        self.assertEqual(done.data["text"], GOOD)
        self.assertIn("web_search", [event.data.get("name") for event in events
                                     if event.kind == "tool_start"])

    def test_second_round_without_evidence_adds_note(self):
        provider = NeverSearchProvider()
        events = self.run_turn(provider, claim_audit=False)
        self.assertEqual(len(provider.calls), 2)     # 补轮一次，不无限循环
        done = [event for event in events if event.kind == "done"][-1]
        self.assertIn("未查证", done.data["text"])

    def test_ops_shadow_records_gate_without_applying(self):
        provider = NeverSearchProvider()
        events = self.run_turn(provider, ops_mode="shadow", ops_gate="shadow",
                               claim_audit=False)
        self.assertEqual(len(provider.calls), 1)
        first_user = provider.calls[0]["messages"][-1]["content"][0]["text"]
        self.assertNotIn("先取证", first_user)
        gates = [event for event in events if event.kind == "gate"]
        self.assertEqual(len(gates), 1)
        self.assertTrue(gates[0].data["needed"])
        self.assertFalse(gates[0].data["applied"])

    def test_shadow_only_traces(self):
        provider = NeverSearchProvider()
        events = self.run_turn(provider, ops_gate="shadow", claim_audit=False)
        self.assertEqual(len(provider.calls), 1)
        first_user = provider.calls[0]["messages"][-1]["content"][0]["text"]
        self.assertNotIn("先取证", first_user)
        gates = [event for event in events if event.kind == "gate"]
        self.assertEqual(len(gates), 1)
        self.assertFalse(gates[0].data["applied"])
        done = [event for event in events if event.kind == "done"][-1]
        self.assertEqual(done.data["text"], BAD)


if __name__ == "__main__":
    unittest.main(verbosity=2)
