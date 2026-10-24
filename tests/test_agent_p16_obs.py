"""P16.3：usage 归一化、成本估算、多轮 token 合计。"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest

from learnsys.agent import cost, loop
from learnsys.llm.config import AgentConfig
from learnsys.agent.events import AgentEvent
from learnsys.llm.provider_anthropic import (
    ProviderEvent,
    ProviderResult,
    ToolCall,
)
from learnsys.server import routes_agent


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    base = AgentConfig(
        base_url="http://127.0.0.1:9/v1", auth_token="t", model="m",
        fast_model="f", max_tokens=1024, thinking=False,
        vision_base_url="", vision_api_key="", vision_model="",
        data_root=root, profile_path=root / "p.md")
    return dataclasses.replace(base, **overrides)


class CostTest(unittest.TestCase):
    def test_anthropic_usage_normalized(self):
        counts = cost.normalize_usage({
            "input_tokens": 100,
            "cache_read_input_tokens": 1000,
            "cache_creation_input_tokens": 200,
            "output_tokens": 50,
        })
        self.assertEqual(counts["prompt_tokens"], 1300)
        self.assertEqual(counts["uncached_tokens"], 100)
        self.assertEqual(counts["cache_read_tokens"], 1000)
        self.assertEqual(counts["cache_write_tokens"], 200)
        self.assertEqual(counts["total_tokens"], 1350)

    def test_openai_usage_normalized(self):
        counts = cost.normalize_usage({
            "prompt_tokens": 1100,
            "prompt_cache_hit_tokens": 1000,
            "completion_tokens": 50,
        })
        self.assertEqual(counts["prompt_tokens"], 1100)
        self.assertEqual(counts["uncached_tokens"], 100)
        self.assertEqual(counts["cache_read_tokens"], 1000)
        self.assertEqual(counts["total_tokens"], 1150)

    def test_estimate_uses_configured_prices(self):
        cfg = make_cfg(pathlib.Path(tempfile.gettempdir()),
                       price_input=1.0, price_output=2.0,
                       price_cache_read=0.1, currency="USD")
        amount, currency, note = cost.estimate({
            "input_tokens": 100,
            "cache_read_input_tokens": 1000,
            "output_tokens": 50,
        }, cfg)
        self.assertEqual(note, "")
        self.assertEqual(currency, "USD")
        self.assertAlmostEqual(amount, 0.0003, places=6)

    def test_estimate_without_prices(self):
        cfg = make_cfg(pathlib.Path(tempfile.gettempdir()))
        amount, currency, note = cost.estimate({"input_tokens": 10}, cfg)
        self.assertEqual(amount, 0.0)
        self.assertEqual(currency, "")
        self.assertIn("未配置单价", note)


class _UsageProvider:
    def __init__(self):
        self.calls = 0

    def stream_messages(self, cfg, system, messages, tools, *, abort=None,
                        response_sink=None):
        self.calls += 1
        if self.calls == 1:
            yield ProviderEvent("done", result=ProviderResult(
                text="先查。",
                tool_calls=[ToolCall("t1", "today_summary", {})],
                content_blocks=[
                    {"type": "text", "text": "先查。"},
                    {"type": "tool_use", "id": "t1", "name": "today_summary",
                     "input": {}}],
                stop_reason="tool_use",
                usage={"input_tokens": 10, "output_tokens": 5,
                       "cache_read_input_tokens": 100}))
        else:
            yield ProviderEvent("done", result=ProviderResult(
                text="查完了。", stop_reason="end_turn",
                usage={"input_tokens": 20, "output_tokens": 7,
                       "cache_read_input_tokens": 300}))


class LoopUsageTest(unittest.TestCase):
    def test_usage_sums_across_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            events = list(loop.run(loop.AgentRequest("今天学了什么"),
                                   provider=_UsageProvider(), cfg=cfg))
            done = events[-1]
            self.assertEqual(done.kind, "done")
            self.assertEqual(done.data["model_calls"], 2)
            self.assertEqual(done.data["tool_calls"], 1)
            usage = done.data["usage"]
            self.assertEqual(usage["input_tokens"], 30)
            self.assertEqual(usage["output_tokens"], 12)
            self.assertEqual(usage["cache_read_input_tokens"], 400)


class TracePrivacyTest(unittest.TestCase):
    def test_write_payload_is_redacted_in_trace(self):
        event = AgentEvent("tool_start", data={
            "name": "save_material_note",
            "input": {"title": "私密笔记", "content": "很长的私人正文" * 100},
        })
        trace = routes_agent._trace_event(event)
        self.assertNotIn("私人正文", str(trace))
        self.assertIn("摘要", trace["data"]["input"])
        self.assertIn("私密笔记", trace["data"]["input"]["摘要"])

    def test_run_code_only_keeps_summary(self):
        event = AgentEvent("tool_start", data={
            "name": "run_code",
            "input": {"language": "cpp", "code": "int main(){" + "x" * 800},
        })
        trace = routes_agent._trace_event(event)
        self.assertNotIn("x" * 100, str(trace))
        self.assertIn("运行代码", trace["data"]["input"]["摘要"])


if __name__ == "__main__":
    unittest.main()
