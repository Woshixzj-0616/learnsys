# -*- coding: utf-8 -*-
"""自动路由（影子优先）：规则、优先级、影子不改行为。"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest

from learnsys.agent import loop, router
from learnsys.agent.config import AgentConfig
from learnsys.agent.provider_anthropic import ProviderEvent, ProviderResult


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    base = AgentConfig(
        base_url="https://api.deepseek.com/anthropic",
        auth_token="test-token",
        model="deepseek-flash",
        fast_model="deepseek-flash",
        strong_model="deepseek-v4-pro",
        max_tokens=8192,
        thinking=False,
        vision_base_url="", vision_api_key="", vision_model="glm-4v-flash",
        data_root=root,
        profile_path=root / "学习档案.md",
        speed="balanced",
        auto_route="shadow",
    )
    return dataclasses.replace(base, **overrides)


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_short_fact_stays_standard(self):
        decision = router.decide(make_cfg(self.root), mode="explain", message="RBAC 是什么？")
        self.assertEqual(decision.tier, "standard")
        self.assertEqual(decision.model, "deepseek-flash")
        self.assertFalse(decision.thinking)
        self.assertEqual(decision.recommended["tier"], "standard")

    def test_hard_question_recommends_deep_in_shadow(self):
        decision = router.decide(
            make_cfg(self.root), mode="explain",
            message="为什么并发下会死锁？从内存模型和锁的顺序推导一下")
        self.assertEqual(decision.tier, "standard")          # 影子：实际不变
        self.assertEqual(decision.recommended["tier"], "deep")
        self.assertEqual(decision.recommended["model"], "deepseek-v4-pro")
        self.assertTrue(decision.recommended["thinking"])
        # 理由只写真正命中的因素，别把未参与的条件也列上。
        self.assertIn("难度词", decision.recommended["reason"])
        self.assertNotIn("对话轮次", decision.recommended["reason"])

    def test_on_applies_deep(self):
        decision = router.decide(
            make_cfg(self.root, auto_route="on"), mode="explain",
            message="为什么并发下会死锁？从内存模型和锁的顺序推导一下")
        self.assertEqual(decision.tier, "deep")
        self.assertEqual(decision.model, "deepseek-v4-pro")
        self.assertTrue(decision.thinking)
        self.assertFalse(decision.concise)

    def test_quick_mode_always_fast(self):
        decision = router.decide(make_cfg(self.root), mode="quick", message="翻译这句话")
        self.assertEqual(decision.tier, "fast")
        self.assertEqual(decision.model, "deepseek-flash")
        self.assertFalse(decision.thinking)

    def test_manual_route_wins(self):
        decision = router.decide(
            make_cfg(self.root, auto_route="on", routes={"explain": "route-model"}),
            mode="explain", message="为什么并发下会死锁？从内存模型和锁的顺序推导一下")
        self.assertEqual(decision.tier, "manual")
        self.assertEqual(decision.model, "route-model")
        self.assertIsNone(decision.recommended)

    def test_speed_deep_is_not_downgraded(self):
        decision = router.decide(
            make_cfg(self.root, speed="deep"), mode="explain", message="一句话")
        self.assertEqual(decision.tier, "deep")
        self.assertEqual(decision.model, "deepseek-flash")   # 手动 deep 不自动换强模型
        self.assertTrue(decision.thinking)
        self.assertFalse(decision.concise)

    def test_speed_fast_is_not_upgraded(self):
        decision = router.decide(
            make_cfg(self.root, speed="fast"), mode="explain",
            message="为什么并发下会死锁？从内存模型和锁的顺序推导一下")
        self.assertEqual(decision.tier, "fast")
        self.assertFalse(decision.thinking)

    def test_strong_model_missing_falls_back_to_main(self):
        decision = router.decide(
            make_cfg(self.root, auto_route="on", strong_model=""), mode="explain",
            message="为什么并发下会死锁？从内存模型和锁的顺序推导一下")
        self.assertEqual(decision.tier, "deep")
        self.assertEqual(decision.model, "deepseek-flash")

    def test_auto_route_off_has_no_recommendation(self):
        decision = router.decide(
            make_cfg(self.root, auto_route="off"), mode="explain",
            message="为什么并发下会死锁？从内存模型和锁的顺序推导一下")
        self.assertEqual(decision.tier, "standard")
        self.assertIsNone(decision.recommended)


class _CapturingProvider:
    def __init__(self):
        self.model = ""
        self.system = ""

    def stream_messages(self, cfg, system, messages, tools, *, abort=None,
                        response_sink=None):
        self.model = cfg.model
        self.system = system
        yield ProviderEvent("done", result=ProviderResult(text="好", stop_reason="end_turn"))


class LoopRouteEventTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_shadow_logs_but_keeps_model(self):
        cfg = make_cfg(self.root, auto_route="shadow")
        provider = _CapturingProvider()
        events = list(loop.run(
            loop.AgentRequest("为什么并发下会死锁？从内存模型和锁的顺序推导一下"),
            provider=provider, cfg=cfg))
        routes = [event for event in events if event.kind == "route"]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].data["recommended"]["tier"], "deep")
        self.assertEqual(provider.model, "deepseek-flash")   # 影子不改实际模型

    def test_on_switches_model_and_prompt(self):
        cfg = make_cfg(self.root, auto_route="on")
        provider = _CapturingProvider()
        list(loop.run(
            loop.AgentRequest("为什么并发下会死锁？从内存模型和锁的顺序推导一下"),
            provider=provider, cfg=cfg))
        self.assertEqual(provider.model, "deepseek-v4-pro")
        self.assertIn("回答长度：深入", provider.system)

    def test_off_emits_no_route_event(self):
        cfg = make_cfg(self.root, auto_route="off")
        provider = _CapturingProvider()
        events = list(loop.run(loop.AgentRequest("RBAC 是什么？"),
                               provider=provider, cfg=cfg))
        self.assertFalse([event for event in events if event.kind == "route"])


if __name__ == "__main__":
    unittest.main()
