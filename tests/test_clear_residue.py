# -*- coding: utf-8 -*-
"""负责人真机反馈：清空/新会话后答案区还留着旧会话残影（页面叠加）。

根因：横栏是 `WA_TranslucentBackground` + 阴影效果，内容变了不强制重画
就会留旧像素。逻辑层 `toPlainText()` 早就是空的 —— 是**像素残影**。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtWidgets  # noqa: E402

from learnsys.ask import bar  # noqa: E402


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TestClearLeavesNoResidue(unittest.TestCase):
    """清空/新会话后：文本空、答案区隐藏、且**强制重画**过（防像素残影）。"""

    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def _fill(self, question: str, answer: str) -> None:
        self.b._start_turn(question)
        seq = self.b._turn_seq
        self.b._on_chunk(answer, replace=False, seq=seq)
        self.b._finish(question, answer, None, seq, "text", "")

    def test_clear_session_wipes_answer(self):
        self._fill("第一问", "答案内容一二三")
        self.assertFalse(self.b.answer.toPlainText() == "")
        self.b.clear_session()
        self.assertEqual(self.b.answer.toPlainText(), "")
        self.assertTrue(self.b.answer.isHidden())   # offscreen 下用 isHidden，别用 isVisible

    def test_new_session_wipes_answer(self):
        self._fill("第一问", "答案内容一二三")
        self.b.new_session()
        self.assertEqual(self.b.answer.toPlainText(), "")
        self.assertTrue(self.b.answer.isHidden())

    def test_clear_after_history_wipes_answer(self):
        self.b._show_past("历史问", "历史答", "text", "")
        self.assertFalse(self.b.answer.toPlainText() == "")
        self.b.clear_session()
        self.assertEqual(self.b.answer.toPlainText(), "")
        self.assertTrue(self.b.answer.isHidden())

    def test_reset_calls_force_repaint(self):
        """关键：清完必须强制重画 —— 否则半透明+阴影会留旧内容像素。"""
        with mock.patch.object(self.b, "_force_repaint") as rep:
            self.b._reset_answer()
        rep.assert_called()

    def test_show_message_calls_force_repaint(self):
        """状态文字一显隐也牵动布局，同样要重画。"""
        with mock.patch.object(self.b, "_force_repaint") as rep:
            self.b.show_message("测试")
        rep.assert_called()

    def test_force_repaint_updates_viewport_and_card(self):
        with mock.patch.object(self.b.answer.viewport(), "repaint") as v, \
             mock.patch.object(self.b.card, "repaint") as c, \
             mock.patch.object(self.b, "repaint") as r:
            self.b._force_repaint()
        v.assert_called()
        c.assert_called()
        r.assert_called()

    def test_reset_resets_answer_start_and_turns(self):
        self._fill("问", "答")
        self.b._show_past("历史问", "历史答", "text", "")
        self.b.new_session()
        self.assertIsNone(self.b._answer_start)
        self.assertEqual(self.b._turns, [])
        self.assertFalse(self.b._showing_history)


if __name__ == "__main__":
    unittest.main(verbosity=2)
