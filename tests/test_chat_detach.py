# -*- coding: utf-8 -*-
"""问一问：运行与连接解耦。

- 没有订阅者（body 不被读取）时，后台仍要跑完并落库；
- 中途出错时，已经流出的正文要保住，不能只剩一句报错。
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from learnsys import config as app_config
from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.server.routes_agent import chat as chat_module


class ChatDetachTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        self.root_patch = mock.patch.object(
            app_config, "DATA_ROOT", pathlib.Path(self.tmp.name))
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        store.connect(self.db_path).close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _wait_assistant(self, timeout: float = 5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            conn = store.connect(self.db_path)
            try:
                rows = store.conversation_messages(conn, 1)
            finally:
                conn.close()
            if any(item.get("role") == "assistant" for item in rows):
                return rows
            time.sleep(0.05)
        self.fail("后台没有把回答落库")

    def test_run_finishes_without_subscriber(self):
        def fake_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("text", text="第一段。")
            time.sleep(0.2)
            yield AgentEvent("text", text="第二段。")
            yield AgentEvent("done", data={"text": "第一段。第二段。", "steps": 1,
                                           "stop_reason": "end_turn"})

        req = chat_module.ChatRequest(message="没人订阅也要跑完")
        with mock.patch("learnsys.server.routes_agent.agent.run", fake_run):
            response = chat_module.chat(req, mock.Mock(), mock.Mock())
        # 故意不读 response.body_iterator：模拟浏览器切页/断开订阅
        self.assertEqual(response.media_type, "text/event-stream")
        rows = self._wait_assistant()
        assistant = [item for item in rows if item.get("role") == "assistant"][-1]
        self.assertEqual(assistant["content"]["text"], "第一段。第二段。")

        conn = store.connect(self.db_path)
        try:
            runs = store.list_agent_runs(conn, limit=5)
        finally:
            conn.close()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["stop_reason"], "end_turn")

    def test_title_takes_first_nonempty_line(self):
        self.assertEqual(chat_module._title_for("1. (程序题, 17分)\n\n基于栈"),
                         "1. (程序题, 17分)")
        self.assertEqual(chat_module._title_for("  \n   \n 真问题"), "真问题")
        self.assertEqual(chat_module._title_for("#include<iostream>\nint main(){}"),
                         "#include<iostream>")
        self.assertEqual(chat_module._title_for(""), "新对话")
        self.assertEqual(chat_module._title_for("字" * 40), "字" * 30)

    def test_history_skips_interrupted_answers(self):
        from learnsys.server.routes_agent.common import _load_history
        conn = store.connect(self.db_path)
        try:
            cid = store.create_conversation(conn, title="测试", module="ask")
            store.add_message(conn, cid, "user", {"text": "q1"})
            store.add_message(conn, cid, "assistant", {"text": "a1"})
            store.add_message(conn, cid, "user", {"text": "q2"})
            store.add_message(conn, cid, "assistant",
                              {"text": "半截", "interrupted": True, "error": "断了"})
            store.add_message(conn, cid, "user", {"text": "q3"})
            store.add_message(conn, cid, "assistant", {"text": "a3"})
            pairs = _load_history(conn, cid, turns=8)
        finally:
            conn.close()
        self.assertEqual(pairs, [("q1", "a1"), ("q3", "a3")])

    def test_partial_text_survives_exception(self):
        def fake_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("text", text="已经写出来的半截。")
            raise RuntimeError("连接断了")

        req = chat_module.ChatRequest(message="中途断流")
        with mock.patch("learnsys.server.routes_agent.agent.run", fake_run):
            chat_module.chat(req, mock.Mock(), mock.Mock())
        rows = self._wait_assistant()
        assistant = [item for item in rows if item.get("role") == "assistant"][-1]
        self.assertEqual(assistant["content"]["text"], "已经写出来的半截。")
        self.assertIn("连接断了", assistant["content"]["error"])
        self.assertTrue(assistant["content"]["interrupted"])


if __name__ == "__main__":
    unittest.main()
