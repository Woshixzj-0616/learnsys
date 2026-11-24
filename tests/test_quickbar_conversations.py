# -*- coding: utf-8 -*-
"""P35.2：快捷栏会话真相（conversations/messages/摘要）与历史回灌。"""
from __future__ import annotations

import os
import pathlib
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.ask.quickbar import bar, workers


def _fake_worker(question: str, display: str = "", conv_id: int = 0):
    return types.SimpleNamespace(
        _question=question,
        _display_text=display or question,
        _mode="explain",
        _conversation_id=conv_id,
    )


class QuickbarConversationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        store.connect(self.db).close()
        self._orig_connect = store.connect
        self.patcher = mock.patch.object(
            workers.store, "connect",
            side_effect=lambda path=None: self._orig_connect(path or self.db))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_first_turn_creates_conversation_and_user_message(self):
        worker = _fake_worker("不要写进标题的正文", display="第一问")
        conv_id, history, summary = workers.start_conversation(worker)
        self.assertGreater(conv_id, 0)
        self.assertEqual(history, [])
        self.assertEqual(summary, "")
        conn = store.connect(self.db)
        try:
            row = store.get_conversation(conn, conv_id)
            self.assertIsNotNone(row)
            self.assertEqual(row[1], "第一问")
            self.assertEqual(row[2], "ask")
            self.assertEqual(row[7], "quickbar")
            messages = store.conversation_messages(conn, conv_id)
        finally:
            conn.close()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"]["text"], "第一问")
        self.assertNotIn("不要写进标题的正文", messages[0]["content"]["text"])

    def test_second_turn_reuses_conversation_and_reads_history(self):
        first = _fake_worker("第一问")
        conv_id, _history, _summary = workers.start_conversation(first)
        workers.save_assistant_message(first, "第一答")
        second = _fake_worker("第二问", conv_id=conv_id)
        same_id, history, summary = workers.start_conversation(second)
        self.assertEqual(same_id, conv_id)
        self.assertEqual(history, [("第一问", "第一答")])
        self.assertEqual(summary, "")

    def test_interrupted_or_error_answers_are_not_history(self):
        worker = _fake_worker("问题")
        conv_id, _history, _summary = workers.start_conversation(worker)
        conn = store.connect(self.db)
        try:
            store.add_message(conn, conv_id, "assistant",
                              {"text": "半截", "interrupted": True})
            store.add_message(conn, conv_id, "user", {"text": "追问"})
            store.add_message(conn, conv_id, "assistant",
                              {"text": "", "error": "断线"})
            store.add_message(conn, conv_id, "user", {"text": "再问"})
            store.add_message(conn, conv_id, "assistant", {"text": "完整回答"})
        finally:
            conn.close()
        conn = store.connect(self.db)
        try:
            pairs = store.conversation_pairs(conn, conv_id)
        finally:
            conn.close()
        self.assertEqual(pairs, [("再问", "完整回答")])

    def test_assistant_message_requests_summary_schedule(self):
        scheduled = []
        with mock.patch("learnsys.agent.post_turn.schedule",
                        side_effect=lambda cid, root: scheduled.append(cid)), \
                mock.patch.object(workers, "load_config",
                                  return_value=types.SimpleNamespace(
                                      data_root=pathlib.Path(self.tmp.name))):
            worker = _fake_worker("第一问")
            conv_id, _h, _s = workers.start_conversation(worker)
            workers.save_assistant_message(worker, "第一答")
            worker2 = _fake_worker("第二问", conv_id=conv_id)
            workers.start_conversation(worker2)
            workers.save_assistant_message(worker2, "第二答")
        # 每写一条 assistant 消息都问一次 schedule；「每 4 条才真跑」由
        # post_turn.schedule 自己判断（已有独立测试）。
        self.assertEqual(scheduled, [conv_id, conv_id])

    def test_save_skips_empty_and_handles_mock_connection(self):
        worker = _fake_worker("问题")
        self.assertFalse(workers.save_assistant_message(worker, ""))
        with mock.patch.object(workers.store, "connect", return_value=mock.Mock()):
            conv_id, history, summary = workers.start_conversation(worker)
            self.assertEqual(conv_id, 0)
            self.assertEqual(history, [])
            self.assertFalse(workers.save_assistant_message(
                _fake_worker("问题", conv_id=9), "答案"))


class QuickbarWorkerConversationTest(unittest.TestCase):
    """跑一次真实 _AskWorker.run（假模型），确认会话/流水/信号都接上。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        store.connect(self.db).close()
        workers.reset_personal_state_cache()
        self._orig_connect = store.connect
        self.patcher = mock.patch.object(
            workers.store, "connect",
            side_effect=lambda path=None: self._orig_connect(path or self.db))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_answered_payload_and_asks_carry_conversation_id(self):
        from learnsys.ask.desktop import sessions
        from learnsys.ask.quickbar import streaming
        sessions_src = pathlib.Path(sessions.__file__).read_text(encoding="utf-8")
        streaming_src = pathlib.Path(streaming.__file__).read_text(encoding="utf-8")
        self.assertIn('conversation_id=record.get("conversation_id")', sessions_src)
        self.assertIn('"conversation_id": int(getattr(self, "_conversation_id"',
                      streaming_src)

    def test_run_writes_conversation_messages_and_run_row(self):
        worker = workers._AskWorker("", "第一问", [], None)
        worker._display_text = "第一问"
        done = []
        worker.done.connect(done.append)
        events = [
            AgentEvent("text", text="第一答"),
            AgentEvent("done", data={
                "text": "第一答", "steps": 1, "model_calls": 1,
                "tool_calls": 0, "stop_reason": "end_turn",
                "model": "test-model",
            }),
        ]

        def fake_run(request, **_kwargs):
            self.assertEqual(request.profile, "assistant.quick")
            self.assertIsNotNone(request.conversation_id)
            yield from events

        with mock.patch.object(workers.agent, "run", fake_run), \
                mock.patch.object(workers, "load_config",
                                  return_value=types.SimpleNamespace(
                                      model="test-model",
                                      data_root=pathlib.Path(self.tmp.name))), \
                mock.patch.object(workers, "personal_state", return_value=""):
            worker.run()

        self.assertEqual(done, ["第一答"])
        conv_id = int(worker._run_info.get("conversation_id") or 0)
        self.assertGreater(conv_id, 0)
        conn = store.connect(self.db)
        try:
            self.assertEqual(store.conversation_pairs(conn, conv_id),
                             [("第一问", "第一答")])
            runs = store.list_agent_runs(conn, limit=5)
        finally:
            conn.close()
        self.assertTrue(runs)
        self.assertEqual(int(runs[0]["conversation_id"] or 0), conv_id)


class QuickbarHistoryReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def test_open_conversation_restores_turns_and_id(self):
        self.b.conversation_loader = lambda cid: {
            "id": cid, "title": "TCP 复习", "summary": "已经聊过三次握手",
            "pairs": [("第一问", "第一答"), ("第二问", "第二答")],
        }
        self.b._open_conversation(12)
        self.assertEqual(self.b._conversation_id, 12)
        self.assertEqual(self.b._turns, [("第一问", "第一答"), ("第二问", "第二答")])
        text = self.b.answer.toPlainText()
        self.assertIn("第一答", text)
        self.assertIn("第二答", text)
        self.assertIn("已经聊过三次握手", text)
        self.assertIn("已接回会话 #12", self.b._status_text)

    def test_show_past_resets_conversation_id(self):
        self.b._conversation_id = 9
        self.b._show_past("旧问", "旧答")
        self.assertEqual(self.b._conversation_id, 0)
        self.assertEqual(self.b._turns, [])


if __name__ == "__main__":
    unittest.main()
