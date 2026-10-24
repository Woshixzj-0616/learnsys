"""Agent 一轮的事件序列（重构 R1.1 的护栏：先锁行为，再拆函数）。

只测「界面收到什么、按什么顺序」，不测模型内容本身。事件种类见
`learnsys/agent/events.py`；这里的断言就是现网行为，拆 `loop.run()` 时不许变。
"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest

from learnsys.agent import loop
from learnsys.agent.config import AgentConfig
from learnsys.agent.provider_anthropic import (
    ProviderError,
    ProviderEvent,
    ProviderResult,
    ToolCall,
)


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    base = AgentConfig(
        base_url="http://127.0.0.1:9/v1",
        auth_token="test-token",
        model="test-model",
        fast_model="test-fast",
        max_tokens=1024,
        thinking=True,
        vision_base_url="",
        vision_api_key="",
        vision_model="glm-4v-flash",
        data_root=root,
        profile_path=root / "学习档案.md",
    )
    return dataclasses.replace(base, **overrides)


def kinds(events) -> list[str]:
    return [event.kind for event in events]


class StreamingTextProvider:
    """正常文本：两个增量，最后 done 给完整正文。"""

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        yield ProviderEvent("text", "第一句")
        yield ProviderEvent("text", "第二句")
        yield ProviderEvent("done", result=ProviderResult(
            text="第一句第二句", stop_reason="end_turn"))


class ToolThenTextProvider:
    """第一次返回工具调用，第二次返回正文；记录第二次是否拿到工具结果。"""

    def __init__(self, call: ToolCall | None = None):
        self.call = call or ToolCall("t1", "today_summary", {})
        self.calls = 0
        self.seen_tool_result = False

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.calls += 1
        if self.calls == 1:
            yield ProviderEvent("text", "我先查一下。")
            yield ProviderEvent("done", result=ProviderResult(
                text="我先查一下。",
                tool_calls=[self.call],
                content_blocks=[
                    {"type": "text", "text": "我先查一下。"},
                    {"type": "tool_use", "id": self.call.id,
                     "name": self.call.name, "input": self.call.input},
                ],
                stop_reason="tool_use",
            ))
            return
        for message in messages:
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    self.seen_tool_result = True
        yield ProviderEvent("text", "查到了。")
        yield ProviderEvent("done", result=ProviderResult(
            text="查到了。", stop_reason="end_turn"))


class ThinkingOnlyThenAnswerProvider:
    """第一次只吐思考（正文为空），重试时给出正文；记录两次的 thinking 开关。"""

    def __init__(self):
        self.thinking_flags: list[bool] = []

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.thinking_flags.append(bool(cfg.thinking))
        if len(self.thinking_flags) == 1:
            yield ProviderEvent("thinking", "先想一想")
            yield ProviderEvent("done", result=ProviderResult(
                thinking="先想一想", stop_reason="end_turn"))
            return
        yield ProviderEvent("text", "快答答案")
        yield ProviderEvent("done", result=ProviderResult(
            text="快答答案", stop_reason="end_turn"))


class BrokenProvider:
    """主模型和轻量模型都连不上。"""

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        raise ProviderError("连不上模型服务")
        yield  # pragma: no cover


class TestAgentEventSequence(unittest.TestCase):
    def run_turn(self, provider, *, cfg_overrides=None, **kwargs):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        cfg = make_cfg(pathlib.Path(root.name), **(cfg_overrides or {}))
        request = kwargs.pop("request", loop.AgentRequest("今天学了什么"))
        return list(loop.run(request, provider=provider, cfg=cfg, **kwargs))

    def test_normal_text(self):
        events = self.run_turn(StreamingTextProvider())
        self.assertEqual(kinds(events), ["text", "text", "done"])
        self.assertEqual(events[0].text, "第一句")
        self.assertEqual(events[1].text, "第二句")
        done = events[-1].data
        self.assertEqual(done["text"], "第一句第二句")
        self.assertEqual(done["stop_reason"], "end_turn")
        self.assertEqual(done["steps"], 1)
        self.assertEqual(done["model_calls"], 1)
        self.assertEqual(done["tool_calls"], 0)

    def test_tool_call_then_answer(self):
        provider = ToolThenTextProvider()
        events = self.run_turn(provider)
        self.assertEqual(kinds(events),
                         ["text", "tool_start", "tool_end", "text", "check", "done"])
        self.assertTrue(provider.seen_tool_result)
        tool_end = events[2].data
        self.assertEqual(tool_end["name"], "today_summary")
        self.assertTrue(tool_end["ok"])
        self.assertTrue(events[4].data["ok"])
        self.assertEqual(events[-1].data["text"], "我先查一下。\n\n查到了。")
        self.assertEqual(events[-1].data["tool_calls"], 1)

    def test_tool_call_denied_keeps_event_order_and_says_not_executed(self):
        provider = ToolThenTextProvider(
            ToolCall("t1", "save_memory", {"content": "以后用中文"}))
        events = self.run_turn(provider, confirm=lambda *_: False)
        self.assertEqual(kinds(events),
                         ["text", "tool_start", "confirm", "tool_end", "text", "done"])
        self.assertEqual(events[1].data["name"], "save_memory")
        self.assertEqual(events[2].data["tool"], "save_memory")
        self.assertIn("写进长期记忆", events[2].data["summary"])
        self.assertTrue(events[3].data["denied"])
        self.assertFalse(events[3].data["ok"])
        self.assertIn("没有执行", events[-1].data["text"])
        self.assertIn("写进长期记忆", events[-1].data["text"])

    def test_thinking_only_retries_with_fast_answer(self):
        provider = ThinkingOnlyThenAnswerProvider()
        events = self.run_turn(provider, cfg_overrides={"speed": "deep"})
        self.assertEqual(kinds(events), ["thinking", "activity", "text", "done"])
        self.assertEqual(events[0].text, "先想一想")
        self.assertIn("正在改用快答重试", events[1].text)
        self.assertEqual(events[-1].data["text"], "快答答案")
        self.assertEqual(events[-1].data["thinking"], "先想一想")
        self.assertEqual(events[-1].data["steps"], 2)
        self.assertEqual(events[-1].data["model_calls"], 2)
        self.assertEqual(provider.thinking_flags, [True, False])

    def test_provider_error_after_fallback(self):
        events = self.run_turn(BrokenProvider())
        self.assertEqual(kinds(events), ["activity", "error"])
        self.assertIn("轻量模型", events[0].text)
        self.assertIn("现在可以", events[-1].text)

    def test_make_plan_events(self):
        provider = ToolThenTextProvider(
            ToolCall("p1", "make_plan", {"steps": ["先查记录", "再总结"]}))
        events = self.run_turn(provider)
        # make_plan 不是普通工具：没有 tool_start，收尾时把 pending 步骤置为 done。
        self.assertEqual(kinds(events),
                         ["text", "plan", "tool_end", "text", "plan_update", "done"])
        self.assertEqual(len(events[1].data["steps"]), 2)
        self.assertEqual(events[1].data["steps"][0]["title"], "先查记录")
        self.assertEqual(events[2].data["preview"], "列了 2 步计划")
        self.assertTrue(events[2].data["ok"])
        self.assertEqual(events[4].data["steps"][0]["status"], "done")


if __name__ == "__main__":
    unittest.main(verbosity=2)
