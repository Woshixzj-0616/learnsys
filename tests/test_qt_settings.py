# -*- coding: utf-8 -*-
"""设置窗口（R3.1）：连接状态、重试、单实例窗口对象。

用假客户端，不碰真实网络与真实 设置.json。
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtWidgets  # noqa: E402

from learnsys import product  # noqa: E402
from learnsys.ask.qt.settings import SettingsWindow  # noqa: E402


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeApiClient(QtCore.QObject):
    ready = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, version: str = "2.20.2", parent=None):
        super().__init__(parent)
        self.version = version
        self.started = 0
        self.calls: list[tuple] = []

    def start(self):
        self.started += 1

    def get(self, path, on_ok, on_err=None):
        self.calls.append(("GET", path, None))

    def post(self, path, body, on_ok, on_err=None):
        self.calls.append(("POST", path, body))

    def delete(self, path, on_ok, on_err=None):
        self.calls.append(("DELETE", path, None))


class TestSettingsWindowSkeleton(unittest.TestCase):
    def setUp(self):
        _app()
        self.api = FakeApiClient()
        self.window = SettingsWindow(self.api)
        self.addCleanup(self.window.deleteLater)

    def test_标题带试点字样(self):
        self.assertIn("Qt 试点", self.window.windowTitle())

    def test_打开时显示正在连接(self):
        self.assertIn("正在连接后台", self.window.status_label.text())
        self.assertFalse(self.window.retry_button.isVisible())

    def test_load_调用客户端_start(self):
        self.window.load()
        self.assertEqual(self.api.started, 1)
        self.assertIn("正在连接后台", self.window.status_label.text())

    def test_连接成功显示版本(self):
        self.window.load()
        self.api.ready.emit()
        self.assertIn(product.PRODUCT_NAME, self.window.status_label.text())
        self.assertIn("v2.20.2", self.window.status_label.text())
        self.assertEqual(self.window.status_label.property("state"), "ok")
        self.assertFalse(self.window.retry_button.isVisible())

    def test_连接失败可重试(self):
        self.window.load()
        self.api.failed.emit("本地服务没起来或已断开。点「重试」再连一次")
        self.assertIn("本地服务没起来", self.window.status_label.text())
        self.assertEqual(self.window.status_label.property("state"), "err")
        # showEvent 之外的 isVisible 在 offscreen 下也不可靠，改查显隐状态
        self.assertFalse(self.window.retry_button.isHidden())

    def test_重试按钮再调_load(self):
        self.window.load()
        self.window.retry_button.click()
        self.assertEqual(self.api.started, 2)

    def test_客户端挂到窗口下(self):
        self.assertIs(self.api.parent(), self.window)


if __name__ == "__main__":
    unittest.main(verbosity=2)
