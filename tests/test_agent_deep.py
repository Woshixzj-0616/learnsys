# -*- coding: utf-8 -*-
"""P25.3 深度分析：复用主模型 key，设置显式覆盖。"""
from __future__ import annotations

import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

from learnsys.agent import deep
from learnsys.llm.config import AgentConfig


def _cfg(**overrides) -> AgentConfig:
    base = dict(
        base_url="https://api.deepseek.com/anthropic",
        auth_token="main-token",
        model="deepseek-flash",
        fast_model="deepseek-flash",
        max_tokens=8192,
        thinking=False,
        vision_base_url="",
        vision_api_key="",
        vision_model="",
        data_root=pathlib.Path("."),
        profile_path=pathlib.Path("."),
        strong_model="deepseek-v4-pro",
    )
    base.update(overrides)
    return AgentConfig(**base)


class DeepConfigTest(unittest.TestCase):
    def test_disabled_by_default(self):
        with mock.patch.object(deep, "_settings", return_value={}):
            self.assertFalse(deep.available())
            info = deep.describe()
            self.assertFalse(info["available"])
            self.assertEqual(info["provider"], "")

    def test_enabled_with_main_key(self):
        with mock.patch.object(deep, "_settings", return_value={"enabled": True}), \
                mock.patch.object(deep, "load_config", return_value=_cfg()):
            self.assertTrue(deep.available())
            info = deep.describe()
            self.assertEqual(info["provider"], "api")
            self.assertEqual(info["model"], "deepseek-v4-pro")
            self.assertNotIn("main-token", str(info))

    def test_enabled_with_explicit_key(self):
        settings = {"enabled": True, "api_key": "deep-token", "model": "m1"}
        with mock.patch.object(deep, "_settings", return_value=settings), \
                mock.patch.object(deep, "load_config", return_value=_cfg(auth_token="")):
            self.assertTrue(deep.available())
            self.assertEqual(deep.describe()["model"], "m1")

    def test_enabled_without_any_key_is_unavailable(self):
        with mock.patch.object(deep, "_settings", return_value={"enabled": True}), \
                mock.patch.object(deep, "load_config",
                                  return_value=_cfg(auth_token="", strong_model="")):
            self.assertFalse(deep.available())

    def test_command_mode_does_not_need_key(self):
        settings = {"enabled": True, "command": "claude", "args": ["-p"]}
        with mock.patch.object(deep, "_settings", return_value=settings), \
                mock.patch.object(deep, "load_config",
                                  return_value=_cfg(auth_token="")):
            self.assertTrue(deep.available())
            info = deep.describe()
            self.assertEqual(info["provider"], "command")
            self.assertEqual(info["model"], "claude")


class DeepApiTest(unittest.TestCase):
    def _stream(self, text="答案"):
        events = [SimpleNamespace(kind="text", text=text),
                  SimpleNamespace(kind="done", result=SimpleNamespace(
                      text=text, usage={"input_tokens": 10, "output_tokens": 5}))]
        return mock.Mock(return_value=events)

    def test_uses_main_model_when_blank(self):
        stream = self._stream()
        recorded = []
        with mock.patch.object(deep, "load_config", return_value=_cfg()), \
                mock.patch.object(deep.provider_anthropic,
                                  "stream_messages", stream), \
                mock.patch.object(deep.agent_usage, "record",
                                  side_effect=lambda *a, **k: recorded.append(k)):
            answer = deep._run_api("问题", {"api_base": "", "api_key": "",
                                            "model": ""})
        self.assertEqual(answer, "答案")
        cfg = stream.call_args.args[0]
        self.assertEqual(cfg.base_url, "https://api.deepseek.com/anthropic")
        self.assertEqual(cfg.auth_token, "main-token")
        self.assertEqual(cfg.model, "deepseek-v4-pro")
        self.assertTrue(cfg.thinking)
        self.assertEqual(recorded[0]["source"], "deep")
        self.assertEqual(recorded[0]["model"], "deepseek-v4-pro")

    def test_explicit_settings_win(self):
        stream = self._stream()
        settings = {"api_base": "https://example.com/anthropic",
                    "api_key": "own-token", "model": "own-model"}
        with mock.patch.object(deep, "load_config", return_value=_cfg()), \
                mock.patch.object(deep.provider_anthropic,
                                  "stream_messages", stream), \
                mock.patch.object(deep.agent_usage, "record"):
            deep._run_api("问题", settings)
        cfg = stream.call_args.args[0]
        self.assertEqual(cfg.base_url, "https://example.com/anthropic")
        self.assertEqual(cfg.auth_token, "own-token")
        self.assertEqual(cfg.model, "own-model")

    def test_missing_key_raises_chinese(self):
        with mock.patch.object(deep, "load_config",
                               return_value=_cfg(auth_token="", strong_model="")):
            with self.assertRaises(RuntimeError) as ctx:
                deep._run_api("问题", {})
        self.assertIn("key", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
