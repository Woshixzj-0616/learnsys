# -*- coding: utf-8 -*-
"""收尾接线：排错题答案经取证审核，问题被打回重写一次。"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest

from learnsys.agent import loop
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult

OPS_QUESTION = "nginx 的 server_name 写 0.0.0.0 会让 nginx -t 报错吗？"
BAD_ANSWER = "根因就是 server_name 不能写 IP。"
GOOD_ANSWER = "最可能的原因是 server_name 匹配不上 Host；需要你运行 nginx -T 确认。"


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    base = AgentConfig(
        base_url="http://127.0.0.1:9/v1",
        auth_token="test-token",
        model="deepseek-flash",
        fast_model="deepseek-flash",
        strong_model="deepseek-v4-pro",
        max_tokens=1024,
        thinking=False,
        vision_base_url="", vision_api_key="", vision_model="glm-4v-flash",
        data_root=root, profile_path=root / "学习档案.md",
        speed="balanced", auto_route="off", ops_mode="on",
    )
    return dataclasses.replace(base, **overrides)


class FabricatingProvider:
    """第一次给没有证据的断言；重写时给修正后的答案。"""

    def __init__(self):
        self.systems: list[str] = []

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.systems.append(system)
        if "校对员" in system:
            yield ProviderEvent("done", result=ProviderResult(
                text=GOOD_ANSWER, stop_reason="end_turn"))
            return
        yield ProviderEvent("text", BAD_ANSWER)
        yield ProviderEvent("done", result=ProviderResult(
            text=BAD_ANSWER, stop_reason="end_turn"))


class OpsFinishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def run_turn(self, **cfg_overrides):
        provider = FabricatingProvider()
        events = list(loop.run(
            loop.AgentRequest(OPS_QUESTION, mode="explain", surface="ask"),
            provider=provider, cfg=make_cfg(self.root, **cfg_overrides)))
        return provider, events

    def test_bad_claim_is_rewritten(self):
        provider, events = self.run_turn()
        kinds = [event.kind for event in events]
        self.assertIn("check", kinds)
        self.assertIn("rewrite", kinds)
        first_check = [event for event in events if event.kind == "check"][0]
        self.assertFalse(first_check.data["ok"])
        self.assertEqual(first_check.data["kind"], "claims")
        self.assertTrue(first_check.data["issues"])
        done = [event for event in events if event.kind == "done"][-1]
        self.assertEqual(done.data["text"], GOOD_ANSWER)
        self.assertEqual(len(provider.systems), 2)
        self.assertIn("先取证", provider.systems[0])

    def test_shadow_does_not_change_answer(self):
        provider, events = self.run_turn(ops_mode="shadow")
        checks = [event for event in events
                  if event.kind == "check" and event.data.get("kind") == "claims"]
        self.assertEqual(checks, [])
        self.assertEqual(len(provider.systems), 1)
        done = [event for event in events if event.kind == "done"][-1]
        self.assertEqual(done.data["text"], BAD_ANSWER)

    def test_claim_audit_off_skips(self):
        provider, events = self.run_turn(claim_audit=False)
        self.assertEqual(len(provider.systems), 1)
        done = [event for event in events if event.kind == "done"][-1]
        self.assertEqual(done.data["text"], BAD_ANSWER)

    def test_plain_question_skips(self):
        provider = FabricatingProvider()
        events = list(loop.run(
            loop.AgentRequest("什么是死锁？", mode="explain", surface="ask"),
            provider=provider, cfg=make_cfg(self.root)))
        checks = [event for event in events
                  if event.kind == "check" and event.data.get("kind") == "claims"]
        self.assertEqual(checks, [])
        self.assertEqual(len(provider.systems), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
