# -*- coding: utf-8 -*-
"""设置窗口（R3.1）：连接状态、重试、单实例窗口对象。

用假客户端，不碰真实网络与真实 设置.json。
"""
from __future__ import annotations

import copy
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


SETTINGS = {
    "agent": {
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-flash",
        "fast_model": "deepseek-flash",
        "strong_model": "deepseek-v4-pro",
        "auto_route": "shadow",
        "max_tokens": 8192,
        "speed": "balanced",
        "price_input": 0.28,
        "price_output": 0.42,
        "price_cache_read": 0.028,
        "currency": "CNY",
        "auth_token_set": True,
        "auth_token_mask": "••••d562",
        "auth_token_source": "env",
    },
    "vision": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4v-flash",
        "api_key_set": True,
        "api_key_mask": "••••1234",
        "api_key_source": "file",
    },
    "hotkey": "alt+q",
    "data_root": r"D:\学习系统",
    "backup_dir": r"D:\学习系统备份",
    "settings_path": r"D:\学习系统\设置.json",
    "modules": {"ask": True, "cet6": False},
}

MODULES = {
    "schema": 2,
    "modules": [
        {"id": "ask", "name": "问一问", "status": "ready"},
        {"id": "cet6", "name": "六级精听", "status": "ready"},
        {"id": "future", "name": "待建页", "status": "planned"},
    ],
}

MEMORY = {
    "items": [
        {"id": 1, "content": "回答和思考一律用中文"},
        {"id": 2, "content": "需要示例代码时用 C"},
    ],
}


class FakeApiClient(QtCore.QObject):
    ready = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, version: str = "2.20.2", parent=None, responses=None):
        super().__init__(parent)
        self.version = version
        self.started = 0
        self.calls: list[tuple] = []
        self.responses = responses if responses is not None else {
            "/api/settings": SETTINGS,
            "/api/modules": MODULES,
            "/api/memory": MEMORY,
        }

    def start(self):
        self.started += 1

    def get(self, path, on_ok, on_err=None):
        self.calls.append(("GET", path, None))
        if path in self.responses:
            on_ok(copy.deepcopy(self.responses[path]))

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


class TestSettingsWindowRender(unittest.TestCase):
    """R3.2：三份数据填满页面，但全部只读。"""

    def setUp(self):
        _app()
        self.api = FakeApiClient()
        self.window = SettingsWindow(self.api)
        self.addCleanup(self.window.deleteLater)
        self.window.load()
        self.api.ready.emit()

    def test_文本模型字段(self):
        expected = {
            "agent-base": "https://api.deepseek.com/anthropic",
            "agent-model": "deepseek-flash",
            "agent-fast": "deepseek-flash",
            "agent-strong": "deepseek-v4-pro",
            "agent-tokens": "8192",
        }
        for key, value in expected.items():
            self.assertEqual(self.window.inputs[key].text(), value, key)
        self.assertEqual(self.window.inputs["agent-auto-route"].currentData(), "shadow")
        self.assertEqual(self.window.inputs["agent-speed"].currentData(), "balanced")

    def test_成本字段(self):
        self.assertEqual(self.window.inputs["price-input"].text(), "0.28")
        self.assertEqual(self.window.inputs["price-output"].text(), "0.42")
        self.assertEqual(self.window.inputs["price-cache"].text(), "0.028")
        self.assertEqual(self.window.inputs["price-currency"].text(), "CNY")

    def test_文本密钥只显示提示(self):
        self.assertEqual(self.window.inputs["agent-token"].text(), "")
        hint = self.window.agent_token_hint.text()
        self.assertIn("来自环境变量", hint)
        self.assertIn("••••d562", hint)

    def test_视觉密钥只显示提示(self):
        self.assertEqual(self.window.inputs["vision-key"].text(), "")
        hint = self.window.vision_key_hint.text()
        self.assertIn("已保存在设置文件", hint)
        self.assertIn("••••1234", hint)

    def test_记忆列表(self):
        self.assertEqual(self.window.memory_list.count(), 2)
        self.assertEqual(self.window.memory_list.item(0).text(), "回答和思考一律用中文")
        self.assertEqual(self.window.memory_list.item(1).text(), "需要示例代码时用 C")

    def test_记忆空状态(self):
        api = FakeApiClient(responses={
            "/api/settings": SETTINGS,
            "/api/modules": MODULES,
            "/api/memory": {"items": []},
        })
        window = SettingsWindow(api)
        self.addCleanup(window.deleteLater)
        window.load()
        window.api.ready.emit()
        self.assertEqual(window.memory_list.count(), 1)
        self.assertIn("还没有记忆", window.memory_list.item(0).text())

    def test_模块复选框与待建标记(self):
        self.assertEqual(len(self.window.module_boxes), 3)
        self.assertTrue(self.window.module_boxes["ask"].isChecked())
        self.assertFalse(self.window.module_boxes["cet6"].isChecked())
        self.assertTrue(self.window.module_boxes["future"].isChecked())
        self.assertTrue(self.window.module_boxes["future"].text().endswith("（待建）"))

    def test_路径与热键(self):
        self.assertEqual(self.window.inputs["hotkey"].text(), "alt+q")
        self.assertEqual(self.window.inputs["data-root"].text(), r"D:\学习系统")
        self.assertIn(r"D:\学习系统\设置.json", self.window.settings_path_label.text())
        self.assertIn(r"D:\学习系统备份", self.window.backup_dir_label.text())

    def test_全部只读(self):
        self.assertTrue(self.window.inputs["agent-model"].isReadOnly())
        self.assertFalse(self.window.inputs["agent-auto-route"].isEnabled())
        self.assertFalse(self.window.memory_list.isEnabled())
        self.assertFalse(self.window.module_boxes["ask"].isEnabled())
        self.assertTrue(self.window.inputs["data-root"].isReadOnly())
        self.assertFalse(self.window.save_button.isEnabled())

    def test_准备三份数据请求(self):
        paths = [call[1] for call in self.api.calls]
        self.assertEqual(paths, ["/api/settings", "/api/modules", "/api/memory"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
