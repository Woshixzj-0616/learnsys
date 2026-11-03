# -*- coding: utf-8 -*-
"""流式断流：没出字走原降级；出过字最多续写一次，不重复已写内容。"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest

from unittest import mock

from learnsys.agent import loop
from learnsys.llm import provider_anthropic
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderError, ProviderEvent, ProviderResult


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    base = AgentConfig(
        base_url="http://127.0.0.1:9/v1",
        auth_token="test-token",
        model="main-model",
        fast_model="fast-model",
        max_tokens=1024,
        thinking=False,
        vision_base_url="", vision_api_key="", vision_model="glm-4v-flash",
        data_root=root, profile_path=root / "学习档案.md",
        speed="balanced",
    )
    return dataclasses.replace(base, **overrides)


def run_turn(provider, **cfg_overrides):
    tmp = tempfile.TemporaryDirectory()
    cfg = make_cfg(pathlib.Path(tmp.name), **cfg_overrides)
    events = list(loop.run(loop.AgentRequest("随便问一句"), provider=provider, cfg=cfg))
    tmp.cleanup()
    return events


class StallThenResumeProvider:
    """第一次先吐一段再断；第二次（续写）吐剩下的。"""

    def __init__(self):
        self.calls: list[dict] = []

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.calls.append({"model": cfg.model, "messages": messages, "tools": tools})
        if len(self.calls) == 1:
            yield ProviderEvent("text", "前半段")
            raise ProviderError("timeout")
        yield ProviderEvent("text", "后半段")
        yield ProviderEvent("done", result=ProviderResult(
            text="后半段", stop_reason="end_turn"))


class FailImmediatelyProvider:
    """主模型一个字都没吐就失败。"""

    def __init__(self):
        self.models: list[str] = []

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.models.append(cfg.model)
        if len(self.models) == 1:
            raise ProviderError("timeout")
        yield ProviderEvent("text", "降级后的回答")
        yield ProviderEvent("done", result=ProviderResult(
            text="降级后的回答", stop_reason="end_turn"))


class AlwaysStallProvider:
    """每次都先吐一点再断。"""

    def __init__(self):
        self.calls = 0

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.calls += 1
        yield ProviderEvent("text", f"片段{self.calls}")
        raise ProviderError("timeout")


class ThinkingThenFailProvider:
    """只吐思考就断：没有正文，不算「已经出字」。"""

    def __init__(self):
        self.models: list[str] = []

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.models.append(cfg.model)
        if len(self.models) == 1:
            yield ProviderEvent("thinking", "先想一想")
            raise ProviderError("timeout")
        yield ProviderEvent("done", result=ProviderResult(
            text="降级的正文", stop_reason="end_turn"))


class ProviderTimeoutTest(unittest.TestCase):
    """流式读超时不再硬编码 90 秒，默认取 cfg.stream_timeout（30 秒）。"""

    class _Response:
        headers = {"Content-Type": "application/json"}

        def read(self):
            return b'{"content": [{"type": "text", "text": "ok"}], ' \
                   b'"stop_reason": "end_turn"}'

        def close(self):
            pass

        def __iter__(self):
            return iter([])

    def _timeout_used(self, cfg, **kwargs):
        used = []

        def fake_urlopen(request, timeout=None):
            used.append(timeout)
            return self._Response()

        with mock.patch.object(provider_anthropic.urllib.request, "urlopen",
                               fake_urlopen):
            list(provider_anthropic.stream_messages(
                cfg, "system",
                [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                **kwargs))
        return used

    def test_default_uses_config_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp), stream_timeout=30.0)
            self.assertEqual(self._timeout_used(cfg), [30.0])

    def test_explicit_timeout_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp), stream_timeout=30.0)
            self.assertEqual(self._timeout_used(cfg, timeout=2.0), [2.0])


class StallTest(unittest.TestCase):
    def test_resumes_once_after_partial_text(self):
        provider = StallThenResumeProvider()
        events = run_turn(provider)
        self.assertEqual(len(provider.calls), 2)
        second = provider.calls[1]["messages"]
        self.assertEqual(second[-2]["role"], "assistant")
        self.assertEqual(second[-2]["content"][0]["text"], "前半段")
        self.assertIn("继续", second[-1]["content"][0]["text"])
        self.assertIsNone(provider.calls[1]["tools"])
        text = "".join(event.text for event in events if event.kind == "text")
        self.assertEqual(text, "前半段后半段")
        done = [event for event in events if event.kind == "done"][-1]
        self.assertEqual(done.data["text"], "前半段后半段")
        retries = [event for event in events
                   if event.kind == "activity" and (event.data or {}).get("retry")]
        self.assertEqual(len(retries), 1)

    def test_immediate_failure_uses_fast_model_not_resume(self):
        provider = FailImmediatelyProvider()
        events = run_turn(provider)
        self.assertEqual(provider.models, ["main-model", "fast-model"])
        activities = [event.text for event in events if event.kind == "activity"]
        self.assertFalse(any("续写" in text for text in activities))
        done = [event for event in events if event.kind == "done"][-1]
        self.assertEqual(done.data["text"], "降级后的回答")

    def test_resume_failure_keeps_partial_text(self):
        provider = AlwaysStallProvider()
        events = run_turn(provider)
        self.assertEqual(provider.calls, 2)          # 最多续写一次
        texts = [event.text for event in events if event.kind == "text"]
        self.assertEqual(texts, ["片段1", "片段2"])
        errors = [event for event in events if event.kind == "error"]
        self.assertTrue(errors)

    def test_claim_audit_off_disables_resume(self):
        provider = AlwaysStallProvider()
        events = run_turn(provider, claim_audit=False)
        self.assertEqual(provider.calls, 1)
        self.assertTrue([event for event in events if event.kind == "error"])

    def test_thinking_only_counts_as_no_text(self):
        provider = ThinkingThenFailProvider()
        events = run_turn(provider)
        self.assertEqual(provider.models, ["main-model", "fast-model"])
        done = [event for event in events if event.kind == "done"][-1]
        self.assertEqual(done.data["text"], "降级的正文")


if __name__ == "__main__":
    unittest.main(verbosity=2)
