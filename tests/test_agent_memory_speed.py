# -*- coding: utf-8 -*-
"""长期记忆 + 回答速度档 + 空正文自动重答。

对应 2026-10-22 那轮反馈：
① 横栏要看得见思考（见 test_quickbar_stream_render）；
② 回答太慢 —— speed 三档 + 精简提示词；
③ 思考用英语 —— 系统提示词里的中文铁律；
④ 强调的事记不住 —— agent_memories 一张表 + save/forget 工具；
⑤ 会话 14 的「答案回来了但是空的」—— 思考-only 时自动快答重试。
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from learnsys import store
from learnsys.agent import loop, memory, prompts, tools
from learnsys.agent.config import AgentConfig
from learnsys.agent.events import AgentEvent
from learnsys.agent.provider_anthropic import ProviderEvent, ProviderResult, _body
from PySide6 import QtCore, QtWidgets

from fastapi.testclient import TestClient

from learnsys.ask import bar
from learnsys.server.app import create_app


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    base = AgentConfig(
        base_url="https://api.deepseek.com/anthropic",
        auth_token="test-token",
        model="deepseek-v4-pro",
        fast_model="deepseek-flash",
        max_tokens=8192,
        thinking=True,
        vision_base_url="", vision_api_key="", vision_model="glm-4v-flash",
        data_root=root,
        profile_path=root / "学习档案.md",
        speed="balanced",
    )
    import dataclasses
    return dataclasses.replace(base, **overrides)


class MemoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.conn = store.connect(self.root / "learning.db")
        self.addCleanup(self.conn.close)

    def test_add_dedupe_and_forget(self):
        first, created = store.add_memory(self.conn, "回答和思考一律用中文")
        self.assertTrue(created)
        again, created_again = store.add_memory(self.conn, "回答和思考一律用中文")
        self.assertEqual(first, again)
        self.assertFalse(created_again)
        self.assertEqual(len(store.list_memories(self.conn)), 1)
        self.assertTrue(store.delete_memory(self.conn, first))
        self.assertEqual(store.list_memories(self.conn), [])
        # 软删除后不算启用
        self.assertEqual(len(store.list_memories(self.conn, include_archived=True)), 1)


class MemoryToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.ctx = tools.ToolContext(data_root=self.root,
                                     db_path=self.root / "learning.db")

    def test_save_injects_into_prompt(self):
        text, _, ok = tools.execute("save_memory", {"content": "示例代码一律用 C/C++"},
                                    self.ctx)
        self.assertTrue(ok)
        self.assertIn("已记住", text)
        rendered = memory.render_for_prompt(self.root)
        self.assertIn("C/C++", rendered)
        self.assertIn("[#", rendered)

    def test_forget_by_id(self):
        tools.execute("save_memory", {"content": "以后用中文回答"}, self.ctx)
        conn = store.connect(self.root / "learning.db")
        memory_id = store.list_memories(conn)[0]["id"]
        conn.close()
        text, _, ok = tools.execute("forget_memory", {"memory_id": memory_id}, self.ctx)
        self.assertTrue(ok)
        self.assertIn("已忘掉", text)
        self.assertNotIn("以后用中文回答", memory.render_for_prompt(self.root))


class PromptTest(unittest.TestCase):
    def test_chinese_thinking_and_memory_are_last_word(self):
        system = prompts.build_system(
            "explain", memories="【用户长期记忆】\n- [#1] 示例代码用 C++",
            concise=True)
        self.assertIn("思考过程一律用中文", system)
        self.assertIn("save_memory", system)
        self.assertIn("示例代码用 C++", system)
        # 记忆必须排在基础口径之后，才能压过默认风格
        self.assertGreater(system.index("示例代码用 C++"),
                           system.index("回答纪律"))

    def test_concise_and_deep_use_different_length_contracts(self):
        concise = prompts.build_system("explain", concise=True)
        deep = prompts.build_system("explain", concise=False)
        self.assertIn("按问题复杂度", concise)
        self.assertIn("≤300 字", concise)
        self.assertNotIn("1200–1800", concise)
        self.assertNotIn("1200–1800", deep)
        self.assertIn("回答长度：深入", deep)
        self.assertIn("1.5 倍", deep)


class SpeedConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_three_speeds(self):
        fast, fast_concise = loop._speed_config(make_cfg(self.root, speed="fast"), "explain")
        self.assertEqual(fast.model, "deepseek-flash")
        self.assertFalse(fast.thinking)
        self.assertTrue(fast_concise)

        balanced, balanced_concise = loop._speed_config(
            make_cfg(self.root, speed="balanced"), "explain")
        self.assertEqual(balanced.model, "deepseek-v4-pro")
        self.assertFalse(balanced.thinking)
        self.assertTrue(balanced_concise)

        deep, deep_concise = loop._speed_config(make_cfg(self.root, speed="deep"), "explain")
        self.assertTrue(deep.thinking)
        self.assertFalse(deep_concise)

    def test_quick_mode_always_fast(self):
        cfg, concise = loop._speed_config(make_cfg(self.root, speed="deep"), "quick")
        self.assertEqual(cfg.model, "deepseek-flash")
        self.assertFalse(cfg.thinking)
        self.assertTrue(concise)

    def test_route_does_not_downgrade_deep(self):
        """任务路由只换模型；deep 仍要思考、仍用深入档。"""
        cfg, concise = loop._speed_config(
            make_cfg(self.root, speed="deep", routes={"explain": "route-model"}), "explain")
        self.assertEqual(cfg.model, "route-model")
        self.assertTrue(cfg.thinking)
        self.assertFalse(concise)

    def test_route_keeps_fast_and_balanced_semantics(self):
        fast, fast_concise = loop._speed_config(
            make_cfg(self.root, speed="fast", routes={"explain": "route-model"}), "explain")
        self.assertEqual(fast.model, "route-model")
        self.assertFalse(fast.thinking)
        self.assertTrue(fast_concise)

        balanced, balanced_concise = loop._speed_config(
            make_cfg(self.root, speed="balanced", routes={"explain": "route-model"}), "explain")
        self.assertEqual(balanced.model, "route-model")
        self.assertFalse(balanced.thinking)
        self.assertTrue(balanced_concise)

    def test_deepseek_body_has_thinking_switch(self):
        cfg = make_cfg(self.root, thinking=False)
        body = _body(cfg, "system", [], None, True)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        body = _body(make_cfg(self.root, thinking=True), "system", [], None, True)
        self.assertEqual(body["thinking"], {"type": "enabled"})

    def test_other_provider_does_not_get_thinking_field(self):
        cfg = make_cfg(self.root, base_url="https://api.example.com/v1")
        self.assertNotIn("thinking", _body(cfg, "system", [], None, True))


class EmptyAnswerRetryTest(unittest.TestCase):
    """会话 14：模型只吐思考、正文空 ⇒ 自动用不思考模式重答，而不是报「空的」。"""

    class _FakeProvider:
        def __init__(self):
            self.calls = []

        def stream_messages(self, cfg, system, messages, tools, *, abort=None, response_sink=None):
            self.calls.append({"thinking": cfg.thinking, "model": cfg.model})
            if cfg.thinking:
                yield ProviderEvent("thinking", text="我想了很久，但没写正文。")
                yield ProviderEvent("done", result=ProviderResult(
                    text="", thinking="我想了很久，但没写正文。", stop_reason="max_tokens"))
            else:
                yield ProviderEvent("text", text="这是重试后的答案。")
                yield ProviderEvent("done", result=ProviderResult(
                    text="这是重试后的答案。", stop_reason="end_turn"))

    def test_retry_without_thinking(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = make_cfg(pathlib.Path(tmp.name), speed="deep")
        provider = self._FakeProvider()
        events = list(loop.run(
            loop.AgentRequest(message="解释一下", use_tools=False),
            provider=provider, cfg=cfg))
        done = [e for e in events if e.kind == "done"][0]
        self.assertEqual(done.data["text"], "这是重试后的答案。")
        self.assertEqual([c["thinking"] for c in provider.calls], [True, False])
        self.assertTrue(any(e.kind == "activity" for e in events))


class MemoryApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        self.orig = store.connect
        patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self.orig(path or self.db_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(create_app(token="t"))
        self.auth = {"X-Learnsys-Token": "t"}

    def test_crud(self):
        added = self.client.post("/api/memory", json={"content": "每次先给结论"},
                                 headers=self.auth)
        self.assertEqual(added.status_code, 200)
        memory_id = added.json()["id"]
        items = self.client.get("/api/memory", headers=self.auth).json()["items"]
        self.assertEqual(items[0]["content"], "每次先给结论")

        updated = self.client.post(f"/api/memory/{memory_id}",
                                   json={"content": "每次先给结论，再展开"},
                                   headers=self.auth)
        self.assertEqual(updated.status_code, 200)
        items = self.client.get("/api/memory", headers=self.auth).json()["items"]
        self.assertIn("再展开", items[0]["content"])

        deleted = self.client.delete(f"/api/memory/{memory_id}", headers=self.auth)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/memory", headers=self.auth).json()["items"], [])


class QuickbarStreamRenderTest(unittest.TestCase):
    """横栏：思考看得见；正文边流边渲染，不会先露 `**` 再变格式。"""

    def setUp(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.app = app
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)
        self.b._start_turn("问题")

    def test_thinking_visible_and_toggle(self):
        self.b._on_thinking("先判断这是语法题。", seq=self.b._turn_seq)
        self.b._render_answer_view()
        self.assertIn("先判断这是语法题", self.b.answer.toPlainText())
        self.b._on_chunk("答案来了", replace=False, seq=self.b._turn_seq)
        self.b._render_answer_view()
        self.assertIn("答案来了", self.b.answer.toPlainText())
        self.b._on_answer_anchor(QtCore.QUrl("think:thinking"))
        self.assertIn("先判断这是语法题", self.b.answer.toPlainText())
        self.b._on_answer_anchor(QtCore.QUrl("think:answer"))
        self.assertIn("答案来了", self.b.answer.toPlainText())

    def test_markdown_rendered_while_streaming(self):
        self.b._on_chunk("**粗体**和 `代码`", replace=False, seq=self.b._turn_seq)
        self.b._render_answer_view()
        text = self.b.answer.toPlainText()
        self.assertIn("粗体", text)
        self.assertNotIn("**", text)
        self.assertIn("代码", text)


class ScrollRegressionTest(unittest.TestCase):
    """会话历史页面被撑出整页滚动：.md 必须给 KaTeX 的 absolute 后代做定位祖先。"""

    def test_md_is_positioned(self):
        css = (pathlib.Path(__file__).resolve().parent.parent
               / "web" / "css" / "ask.css").read_text(encoding="utf-8")
        self.assertIn(".md { position: relative", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
