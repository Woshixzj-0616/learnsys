"""上下文预算：估算、裁剪、共享分配、历史窗口、工具结果。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import prompt_budget
from learnsys.agent import loop, prompts
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult, ToolCall
from tests.test_agent_core import make_cfg


class EstimateTest(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(prompt_budget.estimate_tokens(""), 0)
        self.assertEqual(prompt_budget.estimate_tokens(None), 0)

    def test_chinese_costs_more_than_ascii(self):
        chinese = prompt_budget.estimate_tokens("学习工作台")
        ascii_text = prompt_budget.estimate_tokens("abcdefghij")
        self.assertGreater(chinese, ascii_text)

    def test_messages_sum_text_and_tool_results(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "你好"}]},
            {"role": "user", "content": [{"type": "tool_result",
                                          "content": "结果在这里"}]},
        ]
        self.assertGreater(prompt_budget.estimate_messages(messages), 0)


class ClipTest(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(prompt_budget.clip_tokens("短句", 100), "短句")

    def test_head_tail_keeps_both_ends(self):
        text = "开头" + "中" * 5000 + "结尾"
        clipped = prompt_budget.clip_tokens(text, 300)
        self.assertLessEqual(prompt_budget.estimate_tokens(clipped), 300)
        self.assertTrue(clipped.startswith("开头"))
        self.assertTrue(clipped.endswith("结尾"))
        self.assertIn("已截断", clipped)

    def test_head_and_tail_modes(self):
        text = "开头" + "中" * 5000 + "结尾"
        head = prompt_budget.clip_tokens(text, 200, keep="head")
        tail = prompt_budget.clip_tokens(text, 200, keep="tail")
        self.assertTrue(head.startswith("开头"))
        self.assertFalse(head.endswith("结尾"))
        self.assertTrue(tail.endswith("结尾"))
        self.assertFalse(tail.startswith("开头"))

    def test_zero_budget_is_empty(self):
        self.assertEqual(prompt_budget.clip_tokens("x", 0), "")


class FitSectionsTest(unittest.TestCase):
    def test_fits_and_reports(self):
        sections = {"question": "问题", "context": "上" * 5000,
                    "attachment": "附" * 5000}
        fitted, audit = prompt_budget.fit_sections(sections, 600)
        self.assertTrue(audit["clipped"])
        self.assertEqual(fitted["question"], "问题")     # 问题永不裁
        self.assertLess(prompt_budget.estimate_tokens(fitted["context"]), 5000)
        self.assertLessEqual(audit["after"], 600)

    def test_under_budget_is_untouched(self):
        sections = {"question": "问题", "context": "短上下文"}
        fitted, audit = prompt_budget.fit_sections(sections, 1000)
        self.assertFalse(audit["clipped"])
        self.assertEqual(fitted["context"], "短上下文")

    def test_small_section_does_not_waste_budget(self):
        # attachment 很短，剩余额度应该更多给 context。
        sections = {"question": "问题", "context": "上" * 5000,
                    "attachment": "短附件"}
        fitted, _ = prompt_budget.fit_sections(sections, 800)
        self.assertEqual(fitted["attachment"], "短附件")
        self.assertGreater(prompt_budget.estimate_tokens(fitted["context"]), 300)


class UserTextTest(unittest.TestCase):
    def test_attachment_default_cap(self):
        text = prompts.build_user_text("问题", attachment_text="附" * 8000)
        self.assertLess(prompt_budget.estimate_tokens(text), 4000)
        self.assertIn("参考文档", text)

    def test_prebudgeted_skips_second_cap(self):
        raw = "附" * 8000
        text = prompts.build_user_text("问题", attachment_text=raw,
                                       prebudgeted=True)
        self.assertIn(raw, text)


class HistoryBudgetTest(unittest.TestCase):
    def test_long_answers_are_clipped(self):
        history = [(f"问题{i}", "答" * 5000) for i in range(8)]
        messages = loop._history_messages(history, "", total_tokens=2000)
        self.assertLessEqual(prompt_budget.estimate_messages(messages), 2000)
        self.assertEqual(messages[0]["content"][0]["text"], "问题0")
        self.assertEqual(messages[-2]["content"][0]["text"], "问题7")

    def test_short_history_keeps_eight_turns(self):
        history = [(f"问题{i}", f"回答{i}") for i in range(10)]
        messages = loop._history_messages(history, "")
        self.assertEqual(len(messages), 16)


class _ToolProvider:
    """第一次要工具，第二次记录收到的消息并回答。"""

    def __init__(self):
        self.calls = 0
        self.seen: list[dict] = []

    def stream_messages(self, cfg, system, messages, tools, *, abort=None,
                        response_sink=None):
        self.calls += 1
        if self.calls == 1:
            yield ProviderEvent("done", result=ProviderResult(
                text="查一下", tool_calls=[ToolCall("t1", "today_summary", {})],
                content_blocks=[
                    {"type": "text", "text": "查一下"},
                    {"type": "tool_use", "id": "t1", "name": "today_summary",
                     "input": {}},
                ], stop_reason="tool_use"))
            return
        self.seen = messages
        yield ProviderEvent("done", result=ProviderResult(
            text="结果很长，我已经看完了。", stop_reason="end_turn"))


class ToolResultBudgetTest(unittest.TestCase):
    def test_long_tool_result_is_clipped_for_model(self):
        provider = _ToolProvider()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp), tool_result_tokens=500,
                           tool_turn_tokens=2000)
            wrapped = "x"
            long_raw = "长" * 20000
            with mock.patch("learnsys.agent.turn._execute_tool",
                            return_value=(wrapped, "预览", True, long_raw)):
                events = list(loop.run(loop.AgentRequest("今天学了什么"),
                                       provider=provider, cfg=cfg))
        done = events[-1]
        self.assertEqual(done.kind, "done")
        self.assertLessEqual(done.data["tool_tokens"], 600)
        tool_results = [block for message in provider.seen
                        if message.get("role") == "user"
                        for block in (message.get("content") or [])
                        if block.get("type") == "tool_result"]
        self.assertTrue(tool_results)
        self.assertIn("已按本轮预算截断", tool_results[0]["content"])
        self.assertLess(prompt_budget.estimate_tokens(tool_results[0]["content"]), 700)


class PromptAuditTest(unittest.TestCase):
    def test_done_event_has_prompt_audit(self):
        class Text:
            def stream_messages(self, cfg, system, messages, tools, *,
                                abort=None, response_sink=None):
                yield ProviderEvent("done", result=ProviderResult(
                    text="直接回答。", stop_reason="end_turn"))

        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            events = list(loop.run(loop.AgentRequest("你好", use_tools=False),
                                   provider=Text(), cfg=cfg))
        prompt = events[-1].data["prompt"]
        self.assertEqual(prompt["budget"], prompt_budget.DEFAULT_PROMPT_TOKENS)
        self.assertGreater(prompt["system_tokens"], 0)
        self.assertEqual(prompt["history_turns"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
