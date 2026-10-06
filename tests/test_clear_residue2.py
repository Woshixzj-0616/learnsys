# -*- coding: utf-8 -*-
"""负责人真机反馈「清空/新会话后还有叠加残影」—— 二修。

一修（repaint）不够：offscreen 抓像素证明逻辑和绘制都干净，
真机残影是 **Windows 合成层两层缓存**：
① QGraphicsDropShadowEffect 缓存卡片位图，内容变了不作废就照旧图叠
② WA_TranslucentBackground 分层窗口不逼一下不重合成
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


class TestForceRepaintInvalidatesCaches(unittest.TestCase):
    """清完必须作废阴影缓存 + 逼合成层重刷。"""

    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def test_force_repaint_toggles_shadow_effect(self):
        """阴影效果要关了再开 —— 这是作废位图缓存的关键动作。"""
        eff = self.b.card.graphicsEffect()
        self.assertIsNotNone(eff, "card 应该挂着阴影效果")
        with mock.patch.object(eff, "setEnabled") as se:
            self.b._force_repaint()
        self.assertEqual(se.call_count, 2)
        se.assert_any_call(False)
        se.assert_any_call(True)

    def test_force_repaint_toggles_window_opacity(self):
        """半透明窗口要 0.99→1.0 逼 Windows 重合成。"""
        calls = []
        with mock.patch.object(self.b, "setWindowOpacity",
                               side_effect=lambda v: calls.append(v)):
            self.b._force_repaint()
        self.assertIn(0.99, calls)
        self.assertIn(1.0, calls)

    def test_force_repaint_sync_repaints(self):
        """同步 repaint（不是 update）—— 别排队等事件循环。"""
        with mock.patch.object(self.b.answer.viewport(), "repaint") as v, \
             mock.patch.object(self.b.card, "repaint") as c, \
             mock.patch.object(self.b, "repaint") as r:
            self.b._force_repaint()
        v.assert_called()
        c.assert_called()
        r.assert_called()

    def test_clear_triggers_force_repaint(self):
        with mock.patch.object(self.b, "_force_repaint") as rep:
            self.b._reset_answer()
        rep.assert_called()

    def test_show_message_triggers_force_repaint(self):
        with mock.patch.object(self.b, "_force_repaint") as rep:
            self.b.show_message("测试")
        rep.assert_called()

    def test_clear_after_conversation_leaves_no_text(self):
        """逻辑层：文本必须清干净（这是前提，残影是绘制层的事）。"""
        self.b._start_turn("问题ABCDEF")
        seq = self.b._turn_seq
        self.b._on_chunk("答案XYZ12345", replace=False, seq=seq)
        self.b._finish("问题ABCDEF", "答案XYZ12345", None, seq, "text", "")
        self.b.clear_session()
        self.assertEqual(self.b.answer.toPlainText(), "")
        self.assertTrue(self.b.answer.isHidden())


if __name__ == "__main__":
    unittest.main(verbosity=2)
