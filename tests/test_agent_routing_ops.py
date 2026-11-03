# -*- coding: utf-8 -*-
"""排错题路由：off / shadow / on 三种行为，手动档优先。"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest

from learnsys.agent import intent, router
from learnsys.llm.config import AgentConfig

OPS_MESSAGE = "nginx 的 server_name 写 0.0.0.0 会让 nginx -t 报错吗？"
PLAIN_MESSAGE = "什么是 TCP 三次握手？"


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
        speed="balanced", auto_route="off", ops_mode="shadow",
    )
    return dataclasses.replace(base, **overrides)


class RoutingOpsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.ops = intent.detect_ops(OPS_MESSAGE)
        self.plain = intent.detect_ops(PLAIN_MESSAGE)

    def decide(self, cfg, message=OPS_MESSAGE, ops=None):
        return router.decide(cfg, mode="explain", message=message,
                             ops=self.ops if ops is None else ops)

    def test_on_forces_deep_and_thinking(self):
        decision = self.decide(make_cfg(self.root, ops_mode="on"))
        self.assertEqual(decision.tier, "deep")
        self.assertTrue(decision.thinking)
        self.assertFalse(decision.concise)
        self.assertEqual(decision.model, "deepseek-v4-pro")
        self.assertIn("排错", decision.reason)

    def test_on_without_strong_model_uses_main_model(self):
        decision = self.decide(make_cfg(self.root, ops_mode="on", strong_model=""))
        self.assertEqual(decision.model, "deepseek-flash")
        self.assertTrue(decision.thinking)

    def test_off_ignores_ops(self):
        decision = self.decide(make_cfg(self.root, ops_mode="off"))
        self.assertEqual(decision.tier, "standard")
        self.assertFalse(decision.thinking)
        self.assertNotIn("ops", decision.trace())

    def test_shadow_keeps_route_but_traces_ops(self):
        decision = self.decide(make_cfg(self.root, ops_mode="shadow"))
        self.assertEqual(decision.tier, "standard")
        self.assertFalse(decision.thinking)
        trace = decision.trace()
        self.assertTrue(trace["ops"]["ops"])
        self.assertTrue(trace["ops"]["signals"])
        self.assertEqual(trace["ops"]["recommended"]["tier"], "deep")

    def test_manual_fast_is_respected(self):
        decision = self.decide(make_cfg(self.root, ops_mode="on", speed="fast"))
        self.assertEqual(decision.tier, "fast")
        self.assertFalse(decision.thinking)

    def test_manual_routes_are_respected(self):
        decision = self.decide(make_cfg(self.root, ops_mode="on",
                                        routes={"explain": "route-model"}))
        self.assertEqual(decision.tier, "manual")
        self.assertEqual(decision.model, "route-model")

    def test_quick_mode_stays_fast(self):
        decision = router.decide(make_cfg(self.root, ops_mode="on"),
                                 mode="quick", message=OPS_MESSAGE, ops=self.ops)
        self.assertEqual(decision.tier, "fast")

    def test_plain_question_unchanged(self):
        cfg = make_cfg(self.root, ops_mode="on")
        with_ops = router.decide(cfg, mode="explain", message=PLAIN_MESSAGE,
                                 ops=self.plain)
        without = router.decide(cfg, mode="explain", message=PLAIN_MESSAGE)
        self.assertEqual(with_ops.tier, without.tier)
        self.assertEqual(with_ops.thinking, without.thinking)
        self.assertEqual(with_ops.model, without.model)
        self.assertEqual(with_ops.trace(), without.trace())
        self.assertNotIn("ops", with_ops.trace())


if __name__ == "__main__":
    unittest.main(verbosity=2)
