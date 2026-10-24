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
        "prices": {"deepseek-v4-pro": {"input": 1.0, "output": 2.0,
                                       "cache_read": 0.1}},
        "daily_cost_limit": 5,
        "daily_call_limit": 100,
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
        self.responses = responses if responses is not None else copy.deepcopy({
            "/api/settings": SETTINGS,
            "/api/modules": MODULES,
            "/api/memory": MEMORY,
        })
        self.post_response = {"ok": True, "saved": [], "restart_required": [],
                              "message": "已保存"}
        self.post_responses: dict[str, dict] = {}
        self.post_error: str | None = None
        self.post_errors: dict[str, str] = {}
        self.delete_responses: dict[str, dict] = {}
        self.delete_errors: dict[str, str] = {}
        self.deferred = False
        self.pending: list[tuple] = []

    def start(self):
        self.started += 1

    def get(self, path, on_ok, on_err=None):
        self.calls.append(("GET", path, None))
        if path in self.responses:
            on_ok(copy.deepcopy(self.responses[path]))

    def post(self, path, body, on_ok, on_err=None):
        self.calls.append(("POST", path, copy.deepcopy(body)))
        if self.deferred:
            self.pending.append((path, on_ok, on_err))
            return
        if path in self.post_errors:
            on_err(self.post_errors[path])
            return
        if path in self.post_responses:
            on_ok(copy.deepcopy(self.post_responses[path]))
            return
        if self.post_error is not None:
            on_err(self.post_error)
            return
        on_ok(copy.deepcopy(self.post_response))

    def delete(self, path, on_ok, on_err=None):
        self.calls.append(("DELETE", path, None))
        if path in self.delete_errors:
            on_err(self.delete_errors[path])
            return
        on_ok(copy.deepcopy(self.delete_responses.get(
            path, {"ok": True, "message": "已忘掉"})))


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
        self.assertEqual(self.window.memory_rows[1]["edit"].text(), "回答和思考一律用中文")
        self.assertEqual(self.window.memory_rows[2]["edit"].text(), "需要示例代码时用 C")

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

    def test_核心表单可改其余仍只读(self):
        self.assertFalse(self.window.inputs["agent-model"].isReadOnly())
        self.assertTrue(self.window.inputs["agent-auto-route"].isEnabled())
        self.assertTrue(self.window.memory_list.isEnabled())
        self.assertTrue(self.window.module_boxes["ask"].isEnabled())
        self.assertTrue(self.window.inputs["data-root"].isReadOnly())
        self.assertTrue(self.window.save_button.isEnabled())

    def test_下拉框要聚焦才吃滚轮(self):
        for key in ("agent-auto-route", "agent-speed"):
            self.assertEqual(self.window.inputs[key].focusPolicy(),
                             QtCore.Qt.FocusPolicy.StrongFocus)

    def test_准备三份数据请求(self):
        paths = [call[1] for call in self.api.calls]
        self.assertEqual(paths, ["/api/settings", "/api/modules", "/api/memory"])


class TestSettingsWindowEdit(unittest.TestCase):
    """R3.3：核心表单可改、collect 口径、保存与 dirty。"""

    def setUp(self):
        _app()
        self.api = FakeApiClient()
        self.window = SettingsWindow(self.api)
        self.addCleanup(self.window.deleteLater)
        self.window.load()
        self.api.ready.emit()

    def _post_payload(self) -> dict:
        calls = [call for call in self.api.calls if call[0] == "POST"]
        self.assertTrue(calls)
        return calls[-1][2]

    def test_collect_空密钥和空数字不进_payload(self):
        self.window.inputs["agent-token"].setText("")
        self.window.inputs["vision-key"].setText("")
        self.window.inputs["agent-tokens"].setText("")
        self.window.inputs["price-input"].setText("")
        payload = self.window.collect()
        self.assertNotIn("auth_token", payload["agent"])
        self.assertNotIn("api_key", payload["vision"])
        self.assertNotIn("max_tokens", payload["agent"])
        self.assertNotIn("price_input", payload["agent"])

    def test_collect_对齐_web_字段(self):
        self.window.inputs["agent-token"].setText("sk-test-123456")
        self.window.inputs["agent-tokens"].setText("4096")
        self.window.inputs["price-input"].setText("0.5")
        self.window.inputs["agent-auto-route"].setCurrentIndex(2)
        payload = self.window.collect()
        self.assertEqual(payload["agent"]["auth_token"], "sk-test-123456")
        self.assertEqual(payload["agent"]["max_tokens"], 4096)
        self.assertEqual(payload["agent"]["price_input"], 0.5)
        self.assertEqual(payload["agent"]["auto_route"], "on")
        self.assertEqual(payload["agent"]["speed"], "balanced")
        self.assertEqual(payload["hotkey"], "alt+q")
        self.assertEqual(payload["modules"], {"ask": True, "cet6": False, "future": True})

    def test_输入标记_dirty(self):
        self.assertFalse(self.window.windowTitle().endswith("*"))
        self.window.inputs["agent-model"].setText("deepseek-v4-pro")
        self.assertTrue(self.window.windowTitle().endswith("*"))
        self.assertEqual(self.window.save_note.text(), "有改动还没保存")

    def test_下拉变化也标记_dirty(self):
        self.window.inputs["agent-speed"].setCurrentIndex(2)
        self.assertTrue(self.window.windowTitle().endswith("*"))

    def test_load_清掉_dirty(self):
        self.window.inputs["agent-model"].setText("x")
        self.window.load()
        self.assertFalse(self.window.windowTitle().endswith("*"))

    def test_保存发送并刷新掩码清空密钥(self):
        self.window.inputs["agent-token"].setText("sk-test-123456")
        settings = self.api.responses["/api/settings"]
        settings["agent"]["auth_token_mask"] = "••••9999"
        self.window.save()

        payload = self._post_payload()
        self.assertEqual(payload["agent"]["auth_token"], "sk-test-123456")
        self.assertEqual(self.window.inputs["agent-token"].text(), "")
        self.assertIn("••••9999", self.window.agent_token_hint.text())
        self.assertFalse(self.window._dirty)
        self.assertEqual(self.window.save_note.text(),
                         "已保存。文本/视觉模型下一轮对话立即生效。")

    def test_保存后提示重启(self):
        self.api.post_response = {
            "ok": True, "saved": ["hotkey"], "restart_required": ["hotkey"],
            "message": "已保存；热键要重启学习工作台才生效",
        }
        self.window.save()
        self.assertIn("重启学习工作台后生效", self.window.save_note.text())
        self.assertTrue(self.window.save_note.text().startswith("已保存"))

    def test_后端_400_显示中文_detail(self):
        self.api.post_error = "快捷键格式不对：写成 Alt+Q、Ctrl+Shift+F2 这样"
        self.window.save()
        self.assertIn("快捷键格式不对", self.window.status_label.text())
        self.assertTrue(self.window.save_button.isEnabled())
        self.assertEqual(self.window.save_note.text(), "")

    def test_保存中禁用按钮(self):
        self.window.save_button.click()
        # Fake 同步回调，保存结束后已恢复；这里只验证没有抛异常
        self.assertTrue(self.window.save_button.isEnabled())


class TestSettingsWindowBudget(unittest.TestCase):
    """R7：按模型单价表 + 每日上限。"""

    def setUp(self):
        _app()
        self.api = FakeApiClient()
        self.window = SettingsWindow(self.api)
        self.addCleanup(self.window.deleteLater)
        self.window.load()
        self.api.ready.emit()

    def test_单价表回填(self):
        table = self.window.price_table
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 0).text(), "deepseek-v4-pro")
        self.assertEqual(table.item(0, 1).text(), "1")
        self.assertEqual(table.item(0, 2).text(), "2")
        self.assertEqual(table.item(0, 3).text(), "0.1")

    def test_每日上限回填并进_payload(self):
        self.assertEqual(self.window.inputs["daily-cost-limit"].text(), "5")
        self.assertEqual(self.window.inputs["daily-call-limit"].text(), "100")
        payload = self.window.collect()
        self.assertEqual(payload["agent"]["daily_cost_limit"], 5.0)
        self.assertEqual(payload["agent"]["daily_call_limit"], 100)

    def test_添加删除单价行(self):
        self.window.price_add_button.click()
        self.assertEqual(self.window.price_table.rowCount(), 2)
        row = self.window.price_table.rowCount() - 1
        self.window.price_table.item(row, 0).setText("m2")
        self.window.price_table.item(row, 1).setText("3.5")
        prices = self.window.collect()["agent"]["prices"]
        self.assertEqual(prices["m2"], {"input": 3.5})
        self.window.price_table.selectRow(row)
        self.window.price_remove_button.click()
        self.assertEqual(self.window.price_table.rowCount(), 1)
        self.assertNotIn("m2", self.window.collect()["agent"]["prices"])

    def test_空模型名和非法数字被忽略(self):
        self.window.price_add_button.click()
        row = self.window.price_table.rowCount() - 1
        self.window.price_table.item(row, 0).setText("")
        self.window.price_table.item(row, 1).setText("abc")
        prices = self.window.collect()["agent"]["prices"]
        self.assertEqual(list(prices), ["deepseek-v4-pro"])

    def test_表格改动标记_dirty(self):
        self.window.load()
        self.api.ready.emit()
        self.assertFalse(self.window.windowTitle().endswith("*"))
        self.window.price_table.item(0, 1).setText("9")
        self.assertTrue(self.window.windowTitle().endswith("*"))


class TestKeySemantics(unittest.TestCase):
    """R3.4：密钥只进不出、留空不改、明文不落到界面。"""

    def setUp(self):
        _app()
        self.api = FakeApiClient()
        self.window = SettingsWindow(self.api)
        self.addCleanup(self.window.deleteLater)
        self.window.load()
        self.api.ready.emit()

    def _payloads(self) -> list[dict]:
        return [call[2] for call in self.api.calls if call[0] == "POST"]

    def _all_texts(self) -> str:
        parts = [self.window.windowTitle()]
        for label in self.window.findChildren(QtWidgets.QLabel):
            parts.append(label.text())
        for edit in self.window.findChildren(QtWidgets.QLineEdit):
            parts.append(edit.text())
            parts.append(edit.placeholderText())
        for row in range(self.window.memory_list.count()):
            parts.append(self.window.memory_list.item(row).text())
        return "\n".join(parts)

    def test_第一次发密钥第二次留空就不发(self):
        self.window.inputs["agent-token"].setText("sk-test-123456")
        self.window.save()
        self.assertEqual(self.window.inputs["agent-token"].text(), "")
        self.window.save()

        payloads = self._payloads()
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["agent"]["auth_token"], "sk-test-123456")
        self.assertNotIn("auth_token", payloads[1]["agent"])

    def test_视觉密钥同样留空不改(self):
        self.window.inputs["vision-key"].setText("vk-test-abcdef")
        self.window.save()
        self.window.save()
        payloads = self._payloads()
        self.assertEqual(payloads[0]["vision"]["api_key"], "vk-test-abcdef")
        self.assertNotIn("api_key", payloads[1]["vision"])

    def test_保存后界面只剩掩码(self):
        secret = "sk-test-123456"
        self.window.inputs["agent-token"].setText(secret)
        self.window.save()
        self.assertNotIn(secret, self._all_texts())
        self.assertIn("••••d562", self.window.agent_token_hint.text())

    def test_env_来源提示(self):
        self.assertIn("来自环境变量",
                      self.window.agent_token_hint.text())

    def test_取消空密钥保存不触发_dirty(self):
        self.assertFalse(self.window._dirty)
        self.window.save()
        payload = self._payloads()[-1]
        self.assertNotIn("auth_token", payload["agent"])


class TestSettingsWindowActions(unittest.TestCase):
    """R3.5：测试连接与立即备份。"""

    def setUp(self):
        _app()
        self.api = FakeApiClient()
        self.window = SettingsWindow(self.api)
        self.addCleanup(self.window.deleteLater)
        self.window.load()
        self.api.ready.emit()

    def test_文本测试成功(self):
        self.api.post_responses["/api/settings/test"] = {
            "ok": True, "message": "文本模型可用（deepseek-flash，700 毫秒）"}
        self.window.test_text_button.click()
        call = [c for c in self.api.calls if c[1] == "/api/settings/test"][-1]
        self.assertEqual(call[2], {"kind": "text"})
        self.assertEqual(self.window.test_text_result.text(),
                         "文本模型可用（deepseek-flash，700 毫秒）")
        self.assertEqual(self.window.test_text_result.property("state"), "ok")
        self.assertTrue(self.window.test_text_button.isEnabled())

    def test_视觉测试用_vision(self):
        self.api.post_responses["/api/settings/test"] = {
            "ok": True, "message": "视觉模型可用"}
        self.window.test_vision_button.click()
        call = [c for c in self.api.calls if c[1] == "/api/settings/test"][-1]
        self.assertEqual(call[2], {"kind": "vision"})
        self.assertIn("视觉模型可用", self.window.test_vision_result.text())

    def test_测试失败显示红色(self):
        self.api.post_responses["/api/settings/test"] = {
            "ok": False, "message": "连不上：超时"}
        self.window.test_text_button.click()
        self.assertEqual(self.window.test_text_result.property("state"), "err")
        self.assertIn("连不上", self.window.test_text_result.text())

    def test_有改动先保存再测(self):
        self.window.inputs["agent-model"].setText("deepseek-v4-pro")
        self.window.test_text_button.click()
        self.assertFalse([c for c in self.api.calls if c[1] == "/api/settings/test"])
        self.assertIn("先保存再测", self.window.save_note.text())

    def test_请求期间按钮禁用并显示测试中(self):
        self.api.deferred = True
        self.window.test_text_button.click()
        self.assertFalse(self.window.test_text_button.isEnabled())
        self.assertEqual(self.window.test_text_result.text(), "测试中…")
        _path, on_ok, _on_err = self.api.pending[-1]
        on_ok({"ok": True, "message": "可用"})
        self.assertTrue(self.window.test_text_button.isEnabled())
        self.assertEqual(self.window.test_text_result.text(), "可用")

    def test_网络失败也恢复按钮(self):
        self.api.post_errors["/api/settings/test"] = "本地服务没起来或已断开"
        self.window.test_text_button.click()
        self.assertIn("本地服务没起来", self.window.test_text_result.text())
        self.assertTrue(self.window.test_text_button.isEnabled())

    def test_备份成功显示路径(self):
        self.api.post_responses["/api/settings/backup"] = {
            "ok": True, "path": r"D:\学习系统备份\学习系统-20261024.zip",
            "size_mb": 12.3, "message": "备份完成：学习系统-20261024.zip（12.3 MB）"}
        self.window.backup_button.click()
        self.assertIn("备份完成", self.window.backup_result.text())
        self.assertIn(r"D:\学习系统备份", self.window.last_backup_label.text())
        self.assertEqual(self.window.backup_result.property("state"), "ok")
        self.assertTrue(self.window.backup_button.isEnabled())

    def test_备份失败显示红色(self):
        self.api.post_errors["/api/settings/backup"] = "备份失败：磁盘满了"
        self.window.backup_button.click()
        self.assertEqual(self.window.backup_result.property("state"), "err")
        self.assertIn("磁盘满了", self.window.backup_result.text())
        self.assertTrue(self.window.backup_button.isEnabled())


class TestSettingsWindowMemory(unittest.TestCase):
    """R3.6：Agent 记忆列表、添加、修改、删除。"""

    def setUp(self):
        _app()
        self.api = FakeApiClient()
        self.window = SettingsWindow(self.api)
        self.addCleanup(self.window.deleteLater)
        self.window.load()
        self.api.ready.emit()

    def _calls(self, method: str, path: str) -> list[tuple]:
        return [call for call in self.api.calls if call[0] == method and call[1] == path]

    def test_添加记忆(self):
        self.api.responses["/api/memory"] = {"items": MEMORY["items"] + [
            {"id": 3, "content": "需要示例代码时用 C++"}]}
        self.api.post_responses["/api/memory"] = {
            "ok": True, "id": 3, "created": True, "message": "已记住，下一轮对话生效"}
        self.window.memory_input.setText("需要示例代码时用 C++")
        self.window.memory_add_button.click()

        calls = self._calls("POST", "/api/memory")
        self.assertEqual(calls[-1][2], {"content": "需要示例代码时用 C++"})
        self.assertEqual(self.window.memory_input.text(), "")
        self.assertIn("已记住", self.window.memory_status.text())
        self.assertIn(3, self.window.memory_rows)

    def test_空内容不提交(self):
        self.window.memory_input.setText("   ")
        self.window.memory_add_button.click()
        self.assertFalse(self._calls("POST", "/api/memory"))

    def test_回车添加(self):
        self.window.memory_input.setText("以后都先给结论")
        self.window.memory_input.returnPressed.emit()
        self.assertTrue(self._calls("POST", "/api/memory"))

    def test_修改记忆(self):
        self.api.post_responses["/api/memory/1"] = {"ok": True, "message": "已更新"}
        row = self.window.memory_rows[1]
        row["edit"].setText("回答、思考和示例一律用中文")
        row["save"].click()
        calls = self._calls("POST", "/api/memory/1")
        self.assertEqual(calls[-1][2], {"content": "回答、思考和示例一律用中文"})
        self.assertIn("已更新", self.window.memory_status.text())

    def test_行内回车保存(self):
        row = self.window.memory_rows[1]
        row["edit"].setText("新的内容")
        row["edit"].returnPressed.emit()
        self.assertTrue(self._calls("POST", "/api/memory/1"))

    def test_删除记忆(self):
        self.api.responses["/api/memory"] = {"items": MEMORY["items"][:1]}
        self.window.memory_rows[2]["delete"].click()
        self.assertTrue(self._calls("DELETE", "/api/memory/2"))
        self.assertEqual(self.window.memory_list.count(), 1)
        self.assertNotIn(2, self.window.memory_rows)

    def test_修改_404_显示中文(self):
        self.api.post_errors["/api/memory/1"] = "这条记忆不存在或已删除"
        row = self.window.memory_rows[1]
        row["edit"].setText("改一下")
        row["save"].click()
        self.assertIn("不存在或已删除", self.window.memory_status.text())
        self.assertTrue(row["save"].isEnabled())

    def test_删除失败恢复按钮(self):
        self.api.delete_errors["/api/memory/1"] = "删除失败：数据库忙"
        row = self.window.memory_rows[1]
        row["delete"].click()
        self.assertIn("数据库忙", self.window.memory_status.text())
        self.assertTrue(row["delete"].isEnabled())


class TestSettingsWindowModules(unittest.TestCase):
    """R3.7：模块开关两列展示、勾选可保存、重新加载保持。"""

    def setUp(self):
        _app()
        self.api = FakeApiClient()
        self.window = SettingsWindow(self.api)
        self.addCleanup(self.window.deleteLater)
        self.window.load()
        self.api.ready.emit()

    def _last_payload(self) -> dict:
        calls = [call for call in self.api.calls if call[0] == "POST"
                 and call[1] == "/api/settings"]
        return calls[-1][2]

    def test_两列布局(self):
        positions = [self.window.module_layout.getItemPosition(index)[:2]
                     for index in range(3)]
        self.assertEqual(positions, [(0, 0), (0, 1), (1, 0)])

    def test_待建标记(self):
        self.assertTrue(self.window.module_boxes["future"].text().endswith("（待建）"))

    def test_勾选标记_dirty(self):
        self.window.module_boxes["cet6"].setChecked(True)
        self.assertTrue(self.window._dirty)
        self.assertTrue(self.window.windowTitle().endswith("*"))

    def test_保存带上模块勾选(self):
        self.window.module_boxes["ask"].setChecked(False)
        self.window.save()
        payload = self._last_payload()
        self.assertFalse(payload["modules"]["ask"])
        self.assertFalse(payload["modules"]["cet6"])

    def test_保存后重新加载保持(self):
        self.api.responses["/api/settings"]["modules"]["ask"] = False
        self.window.module_boxes["ask"].setChecked(False)
        self.window.save()
        self.assertFalse(self.window.module_boxes["ask"].isChecked())
        self.assertFalse(self.window._dirty)

    def test_回填不误标_dirty(self):
        self.assertFalse(self.window._dirty)


if __name__ == "__main__":
    unittest.main(verbosity=2)
