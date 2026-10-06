# -*- coding: utf-8 -*-
"""第四轮边角修复的回归测试（#31–#35）。

跑法：.venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtGui, QtWidgets  # noqa: E402

from learnsys import config  # noqa: E402
from learnsys.ask import backend, bar  # noqa: E402


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TestAlwaysOnTopStringFalse(unittest.TestCase):
    """#31 界面设置里 always_on_top 写成字符串 \"false\" 不该变 True。"""

    def test_string_false_reads_as_off(self):
        self.assertFalse(bar._as_bool("false", True))
        self.assertFalse(bar._as_bool("False", True))
        self.assertFalse(bar._as_bool("0", True))
        self.assertFalse(bar._as_bool("关", True))
        self.assertFalse(bar._as_bool(False, True))

    def test_string_true_reads_as_on(self):
        self.assertTrue(bar._as_bool("true", False))
        self.assertTrue(bar._as_bool(True, False))
        self.assertTrue(bar._as_bool("1", False))

    def test_blank_uses_default(self):
        self.assertTrue(bar._as_bool("", True))
        self.assertTrue(bar._as_bool(None, True))
        self.assertFalse(bar._as_bool("", False))


class TestApiStyleValidation(unittest.TestCase):
    """#32 api_style 填错字母不该走错协议，要当没填自动判。"""

    def test_valid_style_honored(self):
        with mock.patch.object(config, "ASK_API_STYLE", "CHAT"):
            self.assertEqual(config.api_style(), "chat")
        with mock.patch.object(config, "ASK_API_STYLE", "responses"):
            self.assertEqual(config.api_style(), "responses")

    def test_invalid_style_falls_back_to_host(self):
        with mock.patch.object(config, "ASK_API_STYLE", "caht"):   # 拼错
            with mock.patch.object(config, "ASK_API_BASE", "https://api.example.com/v1"):
                self.assertEqual(config.api_style(), "chat")

    def test_blank_style_uses_host(self):
        with mock.patch.object(config, "ASK_API_STYLE", ""):
            with mock.patch.object(config, "ASK_API_BASE", "http://127.0.0.1:57321/v1"):
                self.assertEqual(config.api_style(), "responses")


class TestThumbNullPixmap(unittest.TestCase):
    """#33 空截图 pixmap 不该炸在 toImage()。"""

    def test_null_pixmap_returns_blank(self):
        _app()
        out = bar._thumb(QtGui.QPixmap(), 64, 40)
        self.assertFalse(out.isNull())

    def test_none_pixmap_returns_blank(self):
        _app()
        out = bar._thumb(None, 64, 40)
        self.assertFalse(out.isNull())


class TestHistoryRowNullQuestion(unittest.TestCase):
    """#34 历史里 question 为 NULL 不该在 len() 上炸。"""

    def test_null_question_does_not_crash(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        b.history_provider = lambda: [("2026-10-05 12:00:00", None, "答", "text", "")]
        # menu.exec 会阻塞等用户点击 —— 整个 QMenu 换成哑对象，只验「拼菜单那几行不炸」
        with mock.patch.object(bar.QtWidgets, "QMenu") as menu_cls:
            fake_menu = menu_cls.return_value
            fake_menu.addAction.return_value = mock.MagicMock()
            b._show_history()


class TestAnswerCapRecomputedOnShow(unittest.TestCase):
    """#35 答案区高度上限在 show 时重算（分辨率/屏幕可能变了）。"""

    def test_show_recomputes_cap(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        b._answer_cap = 1                                   # 故意写坏
        with mock.patch.object(b, "refresh_usage"):          # 别真去 walk 盘
            b.show()
        self.assertNotEqual(b._answer_cap, 1, "show() 应重算答案区上限")
        self.assertEqual(b._answer_cap, b._calc_answer_cap())


class TestAbortStopsNonStreamPath(unittest.TestCase):
    """#36 非流式返回路径也要认 abort。"""

    def test_abort_before_body_read(self):
        import threading

        class FakeResp:
            headers = {"Content-Type": "application/json"}
            def read(self):
                raise AssertionError("abort 后不该再读 body")
            def close(self):
                pass

        abort = threading.Event()
        abort.set()
        with mock.patch.object(backend, "_open", return_value=FakeResp()):
            with mock.patch.object(backend.config, "api_style", return_value="chat"):
                got = list(backend.ask_stream(None, "问", None, abort=abort))
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
