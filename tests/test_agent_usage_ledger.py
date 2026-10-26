# -*- coding: utf-8 -*-
"""模型调用账本：看图等旁路调用也必须记进 model_usage。"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent import usage, vision
from learnsys.llm.config import _vision_settings, load_config


class _Resp:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class UsageLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db_path = self.root / "learning.db"
        conn = store.connect(self.db_path)
        self.addCleanup(conn.close)
        self.conn = conn
        self.cfg = dataclasses.replace(
            load_config(), data_root=self.root, price_input=2.0,
            price_output=8.0, price_cache_read=0.04, currency="CNY")

    def rows(self):
        return self.conn.execute(
            "SELECT source, model, prompt_tokens, completion_tokens, cost "
            "FROM model_usage ORDER BY id").fetchall()

    def test_record_writes_cost(self):
        amount, currency = usage.record(
            self.root, source="deep", model="test-model",
            usage={"prompt_tokens": 1000, "completion_tokens": 500}, cfg=self.cfg)
        self.assertAlmostEqual(amount, 0.006, places=6)
        self.assertEqual(currency, "CNY")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "deep")
        self.assertEqual(rows[0][1], "test-model")
        self.assertEqual(rows[0][2], 1000)
        self.assertEqual(rows[0][3], 500)

    def test_empty_usage_is_ignored(self):
        usage.record(self.root, source="vision", model="m", usage={}, cfg=self.cfg)
        self.assertEqual(self.rows(), [])

    def test_vision_call_records_usage(self):
        cfg = dataclasses.replace(
            self.cfg, vision_model="glm-4v-flash",
            vision_base_url="https://example.test/v1", vision_api_key="k",
            vision_auth_style="openai", vision_uses_agent=False)
        payload = {
            "choices": [{"message": {"content": "图里有一条箭头从 A 指向 B"}}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 100},
        }
        with mock.patch("learnsys.agent.vision.urllib.request.urlopen",
                        return_value=_Resp(payload)):
            text = vision._call_vision(cfg, "data:image/png;base64,AAAA")
        self.assertIn("箭头", text)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "vision")
        self.assertEqual(rows[0][1], "glm-4v-flash")
        self.assertEqual(rows[0][2], 800)

    def test_vision_reuses_agent_key_when_not_configured(self):
        base, key, model, style, uses_agent = _vision_settings(
            {}, base="https://api.deepseek.com/anthropic",
            token="secret", model="deepseek-v4-pro", fast="deepseek-flash")
        self.assertEqual(base, "https://api.deepseek.com/anthropic")
        self.assertEqual(key, "secret")
        # 复用主配置时优先快模型：v4-pro 不支持图片，flash 支持。
        self.assertEqual(model, "deepseek-flash")
        self.assertEqual(style, "anthropic")
        self.assertTrue(uses_agent)

    def test_explicit_vision_config_wins(self):
        base, key, model, style, uses_agent = _vision_settings(
            {"base_url": "https://open.bigmodel.cn/api/paas/v4",
             "api_key": "glm-key", "model": "glm-4v-plus"},
            base="https://api.deepseek.com/anthropic",
            token="deepseek-key", model="deepseek-flash",
            fast="deepseek-flash")
        self.assertEqual(base, "https://open.bigmodel.cn/api/paas/v4")
        self.assertEqual(key, "glm-key")
        self.assertEqual(model, "glm-4v-plus")
        self.assertEqual(style, "openai")
        self.assertFalse(uses_agent)

    def test_anthropic_style_vision_call(self):
        cfg = dataclasses.replace(
            self.cfg, vision_model="deepseek-flash",
            vision_base_url="https://api.deepseek.com/anthropic",
            vision_api_key="k", vision_auth_style="anthropic",
            vision_uses_agent=True)
        payload = {
            "content": [{"type": "text", "text": "红色圆形，蓝色三角形"}],
            "usage": {"input_tokens": 210, "output_tokens": 25},
        }
        with mock.patch("learnsys.agent.vision.urllib.request.urlopen",
                        return_value=_Resp(payload)) as urlopen:
            text = vision._call_vision(cfg, "data:image/png;base64,AAAA")
        self.assertIn("红色圆形", text)
        request = urlopen.call_args[0][0]
        self.assertTrue(request.full_url.endswith("/anthropic/v1/messages"))
        self.assertEqual(request.get_header("X-api-key"), "k")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "vision")
        self.assertEqual(rows[0][1], "deepseek-flash")
        self.assertEqual(rows[0][2], 210)

    def test_unsupported_image_response_is_error(self):
        cfg = dataclasses.replace(
            self.cfg, vision_model="deepseek-v4-pro",
            vision_base_url="https://example.test/v1", vision_api_key="k",
            vision_auth_style="openai", vision_uses_agent=False)
        payload = {
            "choices": [{"message": {"content": "抱歉，我无法查看这张图片。"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10},
        }
        with mock.patch("learnsys.agent.vision.urllib.request.urlopen",
                        return_value=_Resp(payload)):
            with self.assertRaises(vision.VisionError):
                vision._call_vision(cfg, "data:image/png;base64,AAAA")
        self.assertEqual(self.rows(), [])

    def test_vision_without_usage_writes_nothing(self):
        cfg = dataclasses.replace(
            self.cfg, vision_model="glm-4v-flash",
            vision_base_url="https://example.test/v1", vision_api_key="k",
            vision_auth_style="openai", vision_uses_agent=False)
        payload = {"choices": [{"message": {"content": "只有文字"}}]}
        with mock.patch("learnsys.agent.vision.urllib.request.urlopen",
                        return_value=_Resp(payload)):
            vision._call_vision(cfg, "data:image/png;base64,AAAA")
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
