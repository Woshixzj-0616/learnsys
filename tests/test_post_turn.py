# -*- coding: utf-8 -*-
"""会话收尾：摘要写回、记忆抽取/去重/上限、触发条件、账本。"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent import post_turn
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult


def make_cfg(root: pathlib.Path) -> AgentConfig:
    return AgentConfig(
        base_url="http://127.0.0.1:9/v1",
        auth_token="test-token",
        model="test-model",
        fast_model="test-fast",
        max_tokens=1024,
        thinking=False,
        vision_base_url="",
        vision_api_key="",
        vision_model="glm-4v-flash",
        data_root=root,
        profile_path=root / "学习档案.md",
    )


def fake_stream(payload: dict, seen: list | None = None):
    text = json.dumps(payload, ensure_ascii=False)

    def stream(cfg, system, messages, tools, *, abort=None, response_sink=None,
               **kwargs):
        if seen is not None:
            seen.append(messages)
        yield ProviderEvent("text", text)
        yield ProviderEvent("done", result=ProviderResult(
            text=text, stop_reason="end_turn",
            usage={"input_tokens": 100, "output_tokens": 50}))

    return stream


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, **_rest):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


class PostTurnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db = self.root / "learning.db"
        self.cfg = make_cfg(self.root)
        patcher = mock.patch.object(post_turn, "load_config", return_value=self.cfg)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)

    def _conversation(self, messages: int) -> int:
        conv_id = store.create_conversation(self.conn, title="测试", module="ask")
        for index in range(messages):
            role = "user" if index % 2 == 0 else "assistant"
            store.add_message(self.conn, conv_id, role, {"text": f"第{index}条"})
        return conv_id

    def _run(self, conv_id: int, payload: dict) -> dict:
        with mock.patch.object(post_turn.provider_anthropic, "stream_messages",
                               side_effect=fake_stream(payload)):
            return post_turn.run_once(conv_id, self.root)

    def test_parse_and_fence(self):
        data = post_turn._parse('```json\n{"summary": " 摘 要 ", "memories": []}\n```')
        self.assertEqual(data["summary"], "摘 要")
        self.assertEqual(data["memories"], [])
        self.assertEqual(post_turn._parse("不是 JSON"), {})

    def test_duplicate_detection(self):
        existing = ["回答一律用中文", "我喜欢先看结论再看细节"]
        self.assertTrue(post_turn._duplicate("回答一律用中文。", existing))
        self.assertTrue(post_turn._duplicate("先看结论再看细节", existing))
        self.assertFalse(post_turn._duplicate("写代码时优先用 C++", existing))

    def test_run_once_writes_summary_and_memories(self):
        conv_id = self._conversation(4)
        result = self._run(conv_id, {
            "summary": "用户在问 Python 3.14 的新特性，卡在 GIL。",
            "memories": [
                {"content": "以后回答先给结论", "kind": "preference"},
                {"content": "代码示例默认用 C++", "kind": "preference"},
            ]})
        self.assertEqual(result["memories"], 2)
        row = store.get_conversation(self.conn, conv_id)
        self.assertIn("Python 3.14", row[4])
        self.assertEqual(len(store.list_memories(self.conn)), 2)

    def test_memory_limit_and_dedupe(self):
        store.add_memory(self.conn, "以后回答先给结论")
        conv_id = self._conversation(4)
        result = self._run(conv_id, {
            "summary": "摘要",
            "memories": [
                {"content": "以后回答先给结论"},
                {"content": "代码示例默认用 C++"},
                {"content": "每天先复习再学新的"},
            ]})
        self.assertEqual(result["memories"], 2)      # 去重 1 条 + 上限 2 条
        contents = [item["content"] for item in store.list_memories(self.conn)]
        self.assertIn("代码示例默认用 C++", contents)
        self.assertIn("每天先复习再学新的", contents)
        self.assertEqual(contents.count("以后回答先给结论"), 1)

    def test_summary_rolls_previous_summary_into_prompt(self):
        conv_id = self._conversation(8)
        store.set_conversation_summary(
            self.conn, conv_id, "旧摘要：用户在学 GIL，已经讲清锁。")
        seen = []
        with mock.patch.object(post_turn.provider_anthropic, "stream_messages",
                               side_effect=fake_stream(
                                   {"summary": "新摘要", "memories": []}, seen)):
            post_turn.run_once(conv_id, self.root)
        prompt = seen[0][0]["content"][0]["text"]
        self.assertIn("【已有会话摘要】", prompt)
        self.assertIn("旧摘要：用户在学 GIL", prompt)
        self.assertIn("【最近对话】", prompt)
        row = store.get_conversation(self.conn, conv_id)
        self.assertEqual(row[4], "新摘要")

    def test_transcript_skips_interrupted_answer(self):
        conv_id = self._conversation(2)
        store.add_message(self.conn, conv_id, "user", {"text": "问了一半"})
        store.add_message(self.conn, conv_id, "assistant",
                          {"text": "半截回答", "interrupted": True})
        text = post_turn._transcript(self.conn, conv_id)
        self.assertIn("问了一半", text)
        self.assertNotIn("半截回答", text)

    def test_first_summary_prompt_says_no_previous(self):
        conv_id = self._conversation(4)
        seen = []
        with mock.patch.object(post_turn.provider_anthropic, "stream_messages",
                               side_effect=fake_stream(
                                   {"summary": "首份摘要", "memories": []}, seen)):
            post_turn.run_once(conv_id, self.root)
        prompt = seen[0][0]["content"][0]["text"]
        self.assertIn("【已有会话摘要】\n（无）", prompt)

    def test_usage_recorded(self):
        conv_id = self._conversation(4)
        self._run(conv_id, {"summary": "摘要", "memories": []})
        rows = self.conn.execute("SELECT source FROM model_usage").fetchall()
        self.assertEqual([row[0] for row in rows], ["post_turn"])

    def test_schedule_conditions(self):
        self.assertEqual(post_turn.schedule(self._conversation(3), self.root), False)
        self.assertEqual(post_turn.schedule(self._conversation(4), self.root, internal=True), False)
        with mock.patch.object(post_turn.threading, "Thread", _ImmediateThread), \
                mock.patch.object(post_turn, "_worker") as worker:
            self.assertTrue(post_turn.schedule(self._conversation(4), self.root))
            self.assertFalse(post_turn.schedule(self._conversation(6), self.root))
        worker.assert_called_once()

    def test_worker_swallows_errors(self):
        conv_id = self._conversation(4)
        with mock.patch.object(post_turn, "run_once", side_effect=RuntimeError("模型挂了")):
            post_turn._worker(conv_id, self.root)      # 不抛
        self.assertNotIn(conv_id, post_turn._RUNNING)


if __name__ == "__main__":
    unittest.main()
