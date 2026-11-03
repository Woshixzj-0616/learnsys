# -*- coding: utf-8 -*-
"""新增配置项：默认值、非法值回退、缺省不迁移也能跑。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys.llm import config as llm_config
from learnsys.llm.config import AgentConfig


def base_config(root: pathlib.Path) -> AgentConfig:
    return AgentConfig(
        base_url="https://api.deepseek.com/anthropic",
        auth_token="test-token",
        model="deepseek-flash",
        fast_model="deepseek-flash",
        max_tokens=4096,
        thinking=False,
        vision_base_url="", vision_api_key="", vision_model="glm-4v-flash",
        data_root=root, profile_path=root / "学习档案.md",
    )


class OpsConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def load(self, agent: dict) -> AgentConfig:
        with mock.patch.object(llm_config.app_config, "USER", {"agent": agent}):
            return llm_config.load_config()

    def test_defaults(self):
        cfg = base_config(self.root)
        self.assertEqual(cfg.ops_mode, "shadow")
        self.assertTrue(cfg.claim_audit)
        self.assertEqual(cfg.ops_gate, "shadow")
        self.assertTrue(cfg.summary_guard)
        self.assertEqual(cfg.stream_timeout, 30.0)

    def test_parsed_values(self):
        cfg = self.load({"ops_mode": "on", "claim_audit": "false",
                         "ops_gate": "on", "summary_guard": "false",
                         "stream_timeout": 45})
        self.assertEqual(cfg.ops_mode, "on")
        self.assertFalse(cfg.claim_audit)
        self.assertEqual(cfg.ops_gate, "on")
        self.assertFalse(cfg.summary_guard)
        self.assertEqual(cfg.stream_timeout, 45.0)

    def test_invalid_values_fall_back(self):
        cfg = self.load({"ops_mode": "whatever", "ops_gate": "nope"})
        self.assertEqual(cfg.ops_mode, "shadow")
        self.assertEqual(cfg.ops_gate, "shadow")

    def test_stream_timeout_clamped(self):
        self.assertEqual(self.load({"stream_timeout": 1}).stream_timeout, 10.0)
        self.assertEqual(self.load({"stream_timeout": 999}).stream_timeout, 180.0)

    def test_public_exposes_new_fields(self):
        public = base_config(self.root).public()
        self.assertIn("ops_mode", public)
        self.assertIn("claim_audit", public)
        self.assertIn("ops_gate", public)
        self.assertIn("summary_guard", public)
        self.assertIn("stream_timeout", public)


if __name__ == "__main__":
    unittest.main(verbosity=2)
