# -*- coding: utf-8 -*-
"""Qt 客户端纯函数与令牌流程（R3.1）。

不发真实网络请求：错误文案、健康检查回调、信号都由这里锁住。
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtWidgets  # noqa: E402

from learnsys.ask.qt.api import (TOKEN_ERROR, ApiClient, connection_text,  # noqa: E402
                                 error_text)
from learnsys.ask.qt.settings import key_hint  # noqa: E402


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TestErrorText(unittest.TestCase):
    def test_403_是令牌提示(self):
        self.assertEqual(error_text(403, '{"detail":"缺少或错误的本地令牌"}'), TOKEN_ERROR)

    def test_400_用后端_detail(self):
        self.assertEqual(
            error_text(400, b'{"detail":"\xe5\xbf\xab\xe6\x8d\xb7\xe9\x94\xae\xe6\xa0\xbc\xe5\xbc\x8f\xe4\xb8\x8d\xe5\xaf\xb9"}'),
            "快捷键格式不对")

    def test_非_JSON_用状态码(self):
        self.assertEqual(error_text(500, b"<html>boom</html>"), "请求失败（500）")

    def test_detail_不是字符串时忽略(self):
        self.assertEqual(error_text(422, '{"detail":[{"msg":"x"}]}'), "请求失败（422）")

    def test_空响应体(self):
        self.assertEqual(error_text(400, b""), "请求失败（400）")

    def test_连接失败文案(self):
        self.assertIn("本地服务没起来", connection_text("Connection refused"))
        self.assertIn("Connection refused", connection_text("Connection refused"))


class TestKeyHint(unittest.TestCase):
    def test_未配置(self):
        self.assertEqual(key_hint(False, "", "none"), "未配置")

    def test_来自环境变量(self):
        hint = key_hint(True, "••••d562", "env")
        self.assertEqual(hint, "来自环境变量：••••d562（留空不改）")

    def test_已保存在设置文件(self):
        hint = key_hint(True, "••••3456", "file")
        self.assertEqual(hint, "已保存在设置文件：••••3456（留空不改）")

    def test_有密钥但没掩码用圆点兜底(self):
        self.assertIn("••••", key_hint(True, "", "file"))


class TestApiClientToken(unittest.TestCase):
    def setUp(self):
        _app()
        self.client = ApiClient(8765)
        self.addCleanup(self.client.deleteLater)
        self.ready = []
        self.failed = []
        self.client.ready.connect(lambda: self.ready.append(True))
        self.client.failed.connect(self.failed.append)

    def test_健康响应写令牌与版本(self):
        self.client._health_ok({"token": "abc", "version": "2.20.2"})
        self.assertEqual(self.client.token, "abc")
        self.assertEqual(self.client.version, "2.20.2")
        self.assertEqual(self.ready, [True])
        self.assertEqual(self.failed, [])

    def test_没有令牌就报错(self):
        self.client._health_ok({"ok": True})
        self.assertEqual(self.client.token, "")
        self.assertEqual(self.ready, [])
        self.assertIn("没有本地令牌", self.failed[0])

    def test_有三个方法的回调签名(self):
        for name in ("get", "post", "delete", "start"):
            self.assertTrue(callable(getattr(self.client, name)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
