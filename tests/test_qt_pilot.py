# -*- coding: utf-8 -*-
"""Qt 试点入口（R3.8）：单实例窗口、重复打开只聚焦、每次重新加载。

用假窗口 / 假客户端，不建真实 Qt 窗口、不发网络请求。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys.ask.desktop.qt_pilot import QtPilotMixin  # noqa: E402


class FakeApiClient:
    def __init__(self, port):
        self.port = port


class FakeSettingsWindow:
    instances: list["FakeSettingsWindow"] = []

    def __init__(self, api, parent=None):
        self.api = api
        self.shown = 0
        self.loads = 0
        self.raised = 0
        self.activated = 0
        FakeSettingsWindow.instances.append(self)

    def show(self):
        self.shown += 1

    def raise_(self):
        self.raised += 1

    def activateWindow(self):
        self.activated += 1

    def load(self):
        self.loads += 1


class Host(QtPilotMixin):
    def __init__(self, port):
        self._web_port = port
        self.warnings: list[str] = []

    def _warn(self, message: str) -> None:
        self.warnings.append(message)


class TestQtPilot(unittest.TestCase):
    def setUp(self):
        FakeSettingsWindow.instances.clear()
        patches = [
            mock.patch("learnsys.ask.qt.api.ApiClient", FakeApiClient),
            mock.patch("learnsys.ask.qt.settings.SettingsWindow", FakeSettingsWindow),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_第一次打开建窗口并加载(self):
        host = Host(8765)
        host.open_qt_settings()
        self.assertEqual(len(FakeSettingsWindow.instances), 1)
        window = FakeSettingsWindow.instances[0]
        self.assertEqual(window.api.port, 8765)
        self.assertEqual(window.shown, 1)
        self.assertEqual(window.loads, 1)
        self.assertEqual(window.raised, 1)
        self.assertEqual(window.activated, 1)

    def test_重复打开是同一个窗口并重新加载(self):
        host = Host(8765)
        host.open_qt_settings()
        first = FakeSettingsWindow.instances[0]
        host.open_qt_settings()
        self.assertEqual(len(FakeSettingsWindow.instances), 1)
        self.assertIs(host._qt_settings_window, first)
        self.assertEqual(first.shown, 2)
        self.assertEqual(first.loads, 2)

    def test_服务没起来只提示不建窗口(self):
        host = Host(0)
        host.open_qt_settings()
        self.assertEqual(FakeSettingsWindow.instances, [])
        self.assertTrue(host.warnings)
        self.assertIn("本地服务", host.warnings[0])

    def test_关闭后再打开会重新拉数据(self):
        host = Host(8765)
        host.open_qt_settings()
        window = FakeSettingsWindow.instances[0]
        window.shown = 0                    # 模拟窗口被关掉
        host.open_qt_settings()
        self.assertIs(host._qt_settings_window, window)
        self.assertEqual(window.loads, 2)
        self.assertEqual(window.shown, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
