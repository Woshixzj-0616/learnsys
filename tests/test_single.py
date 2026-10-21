# -*- coding: utf-8 -*-
"""单实例消息：show / background 的分流。"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys.ask import app as app_mod, single  # noqa: E402


class ModeParseTest(unittest.TestCase):
    def test_parse_mode(self):
        self.assertEqual(single.parse_mode(b"show"), "show")
        self.assertEqual(single.parse_mode(b"background"), "background")
        self.assertEqual(single.parse_mode(b""), "show")         # 旧客户端空消息
        self.assertEqual(single.parse_mode(b"junk"), "show")     # 未知消息按正常调用


class CalledBackTest(unittest.TestCase):
    def _bare(self):
        obj = app_mod.AskApp.__new__(app_mod.AskApp)      # 不跑 Qt 初始化
        obj.show_bar = mock.Mock()
        obj.open_web = mock.Mock()
        obj.bar = SimpleNamespace(show_message=mock.Mock())
        return obj

    def test_background_is_silent(self):
        obj = self._bare()
        obj._called_back("background")
        obj.show_bar.assert_not_called()
        obj.open_web.assert_not_called()
        obj.bar.show_message.assert_not_called()

    def test_show_brings_bar_and_workbench(self):
        obj = self._bare()
        obj._called_back("show")
        obj.show_bar.assert_called_once()
        obj.open_web.assert_called_once()

    def test_unknown_mode_acts_like_show(self):
        obj = self._bare()
        obj._called_back("whatever")
        obj.show_bar.assert_called_once()
        obj.open_web.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
