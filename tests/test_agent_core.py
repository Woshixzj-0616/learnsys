"""Agent 核心的单元测试：不连网、不用真实 key、不起界面。"""
from __future__ import annotations

import dataclasses
import datetime
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import config as app_config
from learnsys import store
from learnsys.agent import loop, prompts, tools, vision
from learnsys.agent.config import AgentConfig, clean_model, load_config
from learnsys.agent.events import AgentEvent
from learnsys.agent.provider_anthropic import (
    ProviderError,
    ProviderEvent,
    ProviderResult,
    ToolCall,
    _result_from_blocks,
    iter_sse,
)


def make_cfg(root: pathlib.Path | None = None, **overrides) -> AgentConfig:
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
        data_root=root or pathlib.Path(tempfile.gettempdir()),
        profile_path=(root or pathlib.Path(tempfile.gettempdir())) / "学习档案.md",
    )
    return dataclasses.replace(base, **overrides)


class TestConfig(unittest.TestCase):
    def test_clean_model_strips_context_marker(self):
        self.assertEqual(clean_model("deepseek-flash[1M]"), "deepseek-flash")
        self.assertEqual(clean_model(" deepseek-v4-pro "), "deepseek-v4-pro")
        self.assertEqual(clean_model(""), "")

    def test_load_from_claude_env_fallback(self):
        env = {
            "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "t",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro[1M]",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-flash[1M]",
        }
        with mock.patch.object(app_config, "USER", {}), \
                mock.patch("learnsys.agent.config._claude_env", return_value=env):
            cfg = load_config()
        self.assertTrue(cfg.ready)
        self.assertEqual(cfg.model, "deepseek-v4-pro")
        self.assertEqual(cfg.fast_model, "deepseek-flash")
        self.assertFalse(cfg.vision_ready)

    def test_not_ready_without_token(self):
        cfg = make_cfg(auth_token="")
        events = list(loop.run(loop.AgentRequest("你好"), cfg=cfg))
        self.assertEqual(events[-1].kind, "error")
        self.assertIn("还没配置模型", events[-1].text)


class TestSSE(unittest.TestCase):
    def test_standard_events(self):
        lines = [
            "event: message_start\n",
            'data: {"type":"message_start","message":{"usage":{"input_tokens":3}}}\n',
            "\n",
            "event: content_block_delta\n",
            'data: {"index":0,"delta":{"type":"text_delta","text":"你"}}\n',
            "\n",
            "event: message_stop\n",
            'data: {"type":"message_stop"}\n',
            "\n",
        ]
        got = list(iter_sse(lines))
        self.assertEqual(got[0][0], "message_start")
        self.assertEqual(got[1][0], "content_block_delta")
        self.assertEqual(got[1][1]["delta"]["text"], "你")

    def test_data_only_uses_json_type(self):
        lines = ['data: {"type":"content_block_delta","index":0,'
                 '"delta":{"type":"text_delta","text":"好"}}\n', "\n"]
        got = list(iter_sse(lines))
        self.assertEqual(got[0][0], "content_block_delta")
        self.assertEqual(got[0][1]["delta"]["text"], "好")

    def test_result_from_blocks_with_tool(self):
        blocks = {
            0: {"type": "thinking", "thinking": "想", "signature": "sig"},
            1: {"type": "text", "text": "先查"},
            2: {"type": "tool_use", "id": "t1", "name": "today_summary",
                "input_json": '{"a":1}', "input": {}},
        }
        result = _result_from_blocks(blocks, "tool_use", {})
        self.assertEqual(result.text, "先查")
        self.assertEqual(result.thinking, "想")
        self.assertEqual(result.tool_calls[0].name, "today_summary")
        self.assertEqual(result.tool_calls[0].input, {"a": 1})
        self.assertEqual(result.content_blocks[0]["type"], "thinking")
        self.assertEqual(result.content_blocks[0]["signature"], "sig")


class TestPrompts(unittest.TestCase):
    def test_contract_is_short_by_default(self):
        system = prompts.build_system("explain")
        self.assertIn("按问题复杂度", system)
        self.assertIn("直接给结论", system)
        self.assertIn("Markdown", system)
        # 「想一想」只能作为负面规则出现，不能再是无条件要求
        self.assertNotIn("最后给「想一想」", system)

    def test_code_and_questions_are_opt_in(self):
        system = prompts.build_system("explain")
        self.assertIn("默认不贴代码块", system)
        self.assertIn("按需开启", system)
        self.assertIn("考考我", system)

    def test_style_examples_only_for_explain_standard(self):
        self.assertIn("只学取舍", prompts.build_system("explain"))
        self.assertNotIn("只学取舍", prompts.build_system("quiz"))
        self.assertNotIn("只学取舍", prompts.build_system("guide"))
        self.assertNotIn("只学取舍", prompts.build_system("quick"))
        self.assertNotIn("只学取舍", prompts.build_system("explain", concise=False))

    def test_modes(self):
        self.assertIn("引导式", prompts.build_system("guide"))
        self.assertIn("150 字", prompts.build_system("quick"))
        self.assertIn("5 道题", prompts.build_system("quiz"))

    def test_ocr_note_is_honest(self):
        text = prompts.build_user_text("这图讲什么", image_text="左移 右移",
                                       image_used_vision=False)
        self.assertIn("看不到图", text)
        text2 = prompts.build_user_text("这图讲什么", image_text="左移 右移",
                                        image_used_vision=True)
        self.assertNotIn("看不到图", text2)

    def test_history_puts_image_on_first_turn(self):
        messages = loop._history_messages([("图里是什么", "循环移位")], "图上有箭头")
        self.assertEqual(messages[0]["role"], "user")
        self.assertIn("图上有箭头", messages[0]["content"][0]["text"])
        self.assertIn("图里是什么", messages[0]["content"][0]["text"])


class FakeProvider:
    """假的模型：第一次返回工具调用，第二次返回正文。"""

    def __init__(self):
        self.calls = 0
        self.seen_tool_result = False

    def stream_messages(self, cfg, system, messages, tools, *, abort=None, response_sink=None):
        self.calls += 1
        if self.calls == 1:
            call = ToolCall("t1", "today_summary", {})
            yield ProviderEvent("done", result=ProviderResult(
                text="我先查一下记录。",
                tool_calls=[call],
                content_blocks=[
                    {"type": "text", "text": "我先查一下记录。"},
                    {"type": "tool_use", "id": "t1", "name": "today_summary", "input": {}},
                ],
                stop_reason="tool_use",
            ))
            return
        for message in messages:
            if message.get("role") == "user":
                for block in message.get("content") or []:
                    if block.get("type") == "tool_result":
                        self.seen_tool_result = True
        yield ProviderEvent("text", "今天的记录在这里。")
        yield ProviderEvent("done", result=ProviderResult(
            text="今天的记录在这里。", stop_reason="end_turn"))


class AlwaysToolProvider:
    def stream_messages(self, cfg, system, messages, tools, *, abort=None, response_sink=None):
        yield ProviderEvent("done", result=ProviderResult(
            text="再查",
            tool_calls=[ToolCall("t", "today_summary", {})],
            content_blocks=[{"type": "tool_use", "id": "t", "name": "today_summary", "input": {}}],
            stop_reason="tool_use",
        ))


class TextProvider:
    def __init__(self, text: str):
        self.text = text

    def stream_messages(self, cfg, system, messages, tools, *, abort=None, response_sink=None):
        yield ProviderEvent("done", result=ProviderResult(text=self.text, stop_reason="end_turn"))


class CapturingProvider:
    def __init__(self):
        self.system = ""
        self.tools = "unset"
        self.model = ""

    def stream_messages(self, cfg, system, messages, tools, *, abort=None, response_sink=None):
        self.system = system
        self.model = cfg.model
        self.tools = tools
        yield ProviderEvent("done", result=ProviderResult(text="[]", stop_reason="end_turn"))


class FlakyProvider:
    """主模型第一次连接失败，重试时成功；记录每次用的模型名。"""

    def __init__(self):
        self.models: list[str] = []

    def stream_messages(self, cfg, system, messages, tools, *, abort=None, response_sink=None):
        self.models.append(cfg.model)
        if len(self.models) == 1:
            raise ProviderError("连接断了")
        yield ProviderEvent("done", result=ProviderResult(text="降级成功", stop_reason="end_turn"))


class BrokenProvider:
    def stream_messages(self, cfg, system, messages, tools, *, abort=None, response_sink=None):
        raise ProviderError("连不上模型服务")
        yield  # pragma: no cover

    def close(self):
        pass


class TestAgentLoop(unittest.TestCase):
    def test_tool_then_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            fake = FakeProvider()
            events = list(loop.run(loop.AgentRequest("今天学了什么"), provider=fake, cfg=cfg))
            kinds = [event.kind for event in events]
            self.assertIn("tool_start", kinds)
            self.assertIn("tool_end", kinds)
            self.assertEqual(events[-1].kind, "done")
            self.assertIn("今天的记录在这里", events[-1].data["text"])
            self.assertTrue(fake.seen_tool_result)

    def test_model_route_overrides_speed_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp), speed="balanced",
                           routes={"explain": "route-model"})
            capturing = CapturingProvider()
            list(loop.run(loop.AgentRequest("你好"), provider=capturing, cfg=cfg))
            self.assertEqual(capturing.model, "route-model")

    def test_model_route_missing_falls_back_to_speed_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp), speed="balanced")
            capturing = CapturingProvider()
            list(loop.run(loop.AgentRequest("你好"), provider=capturing, cfg=cfg))
            self.assertEqual(capturing.model, "test-model")

    def test_provider_error_falls_back_to_fast_model(self):
        """主模型连不上时，自动换轻量模型重试，答案照常出来。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp), speed="balanced")
            flaky = FlakyProvider()
            events = list(loop.run(loop.AgentRequest("今天学了什么"),
                                   provider=flaky, cfg=cfg))
            self.assertEqual(flaky.models, ["test-model", "test-fast"])
            self.assertIn("轻量模型", " ".join(
                event.text for event in events if event.kind == "activity"))
            self.assertEqual(events[-1].kind, "done")
            self.assertEqual(events[-1].data["text"], "降级成功")

    def test_both_models_down_gives_chinese_next_steps(self):
        """两个模型都不可用时，给出中文原因 + 现在能做什么，不裸抛异常。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp), speed="balanced")
            events = list(loop.run(loop.AgentRequest("今天学了什么"),
                                   provider=BrokenProvider(), cfg=cfg))
            self.assertEqual(events[-1].kind, "error")
            text = events[-1].text
            self.assertIn("现在可以", text)
            self.assertIn("设置", text)
            self.assertIn("资料库", text)

    def test_max_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            events = list(loop.run(loop.AgentRequest("今天学了什么"),
                                   provider=AlwaysToolProvider(), cfg=cfg, max_steps=3))
            self.assertEqual(events[-1].kind, "error")
            self.assertIn("工具调用次数太多", events[-1].text)

    def test_ocr_fallback_gets_a_visible_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            with mock.patch.object(loop.vision, "describe_images",
                                   return_value=("图上有字", False)):
                events = list(loop.run(
                    loop.AgentRequest("这图讲什么", image_path="fake.png"),
                    provider=TextProvider("这是答案。"), cfg=cfg))
            self.assertTrue(events[-1].data["text"].startswith("（本次没看到原图"))

    def test_banner_not_duplicated_if_model_mentions_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            with mock.patch.object(loop.vision, "describe_images",
                                   return_value=("图上有字", False)):
                events = list(loop.run(
                    loop.AgentRequest("这图讲什么", image_path="fake.png"),
                    provider=TextProvider("根据 OCR 文字，这张图讲的是循环移位。"), cfg=cfg))
            self.assertFalse(events[-1].data["text"].startswith("（本次没看到原图"))

    def test_system_override_and_tools_off(self):
        cfg = make_cfg()
        fake = CapturingProvider()
        list(loop.run(loop.AgentRequest("出计划", system_override="只输出 JSON",
                                        use_tools=False), provider=fake, cfg=cfg))
        self.assertEqual(fake.system, "只输出 JSON")
        self.assertIsNone(fake.tools)

    def test_aborted_before_start(self):
        import threading
        abort = threading.Event()
        abort.set()
        cfg = make_cfg()
        events = list(loop.run(loop.AgentRequest("你好"), cfg=cfg, abort=abort))
        self.assertEqual(events[-1].kind, "done")
        self.assertEqual(events[-1].data["stop_reason"], "aborted")


class TestTools(unittest.TestCase):
    def test_search_records_finds_ask_and_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            today = datetime.date.today()
            day = root / f"{today.year}.{today.month}.{today.day}"
            conn = store.connect(day / "learnsys.db")
            store.add_ask(conn, "二叉树怎么遍历", "前序、中序、后序", 100, "test")
            store.add_transcript(conn, 1, store.now(), store.now(), "今天讲了二叉树的遍历")
            conn.close()
            text = tools.search_records("二叉树", days=7, data_root=root)
            self.assertIn("二叉树怎么遍历", text)
            self.assertIn("课堂转写", text)

    def test_search_records_empty_query_lists_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            today = datetime.date.today()
            day = root / f"{today.year}.{today.month}.{today.day}"
            conn = store.connect(day / "learnsys.db")
            store.add_ask(conn, "栈和队列的区别", "后进先出 / 先进先出", 80, "test")
            conn.close()
            text = tools.search_records("", days=7, data_root=root)
            self.assertIn("栈和队列的区别", text)
            self.assertIn("最近 7 天里的记录", text)

    def test_ocr_rejects_path_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = tools.ToolContext(data_root=pathlib.Path(tmp))
            text = tools.ocr_image("C:/Windows/win.ini", ctx=ctx)
            self.assertIn("不在学习工作台的数据目录", text)


class TestQuickbarMarkdown(unittest.TestCase):
    def test_bold_with_cjk_punctuation(self):
        from learnsys.ask.bar import _markdown_bold_for_qt
        self.assertEqual(_markdown_bold_for_qt("**（同一端）**"),
                         "<b>（同一端）</b>")

    def test_code_fence_untouched(self):
        from learnsys.ask.bar import _markdown_bold_for_qt
        text = "```python\nx = a ** b\n```\n**粗**"
        out = _markdown_bold_for_qt(text)
        self.assertIn("a ** b", out)
        self.assertIn("<b>粗</b>", out)


class TestVision(unittest.TestCase):
    def test_chat_url_variants(self):
        self.assertEqual(vision.chat_url("https://api.siliconflow.cn/v1"),
                         "https://api.siliconflow.cn/v1/chat/completions")
        self.assertEqual(vision.chat_url("https://open.bigmodel.cn/api/paas/v4"),
                         "https://open.bigmodel.cn/api/paas/v4/chat/completions")
        self.assertEqual(vision.chat_url("https://api.openai.com"),
                         "https://api.openai.com/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
