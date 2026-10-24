# -*- coding: utf-8 -*-
"""今日页 Qt 试点（R4）：数据、渲染、跳转、降级、响应式与入口。"""
from __future__ import annotations

import copy
import datetime
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from learnsys.ask.desktop.qt_pilot import QtPilotMixin, open_workbench_link  # noqa: E402
from learnsys.ask.qt.today import TodayWindow, chars_parts, date_label, minutes_parts  # noqa: E402


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


OVERVIEW = {
    "date": "2026-10-24",
    "name": "智坚",
    "today": {"xp": 45, "goal": 100, "percent": 45.0, "asks": 3, "minutes": 30,
              "cet6": 2, "netlab": 1, "review": 1, "quiz": 1},
    "total": {"xp": 315, "level": 2, "title": "布线学徒", "into": 15,
              "need": 500, "percent": 3.0},
    "streak": 6,
    "week": {"active_days": 4, "minutes": 180, "asks": 12},
    "achievements": [],
}

TODAY = {
    "date": "2026-10-24",
    "focus": {"minutes": 30, "switches": 4, "apps": []},
    "asks": [
        {"kind": "image", "question": "图上是什么", "answer": "..."},
        {"kind": "text", "question": "什么是 RBAC", "answer": "..."},
    ],
    "ask_count": 3,
    "transcripts": {"count": 2, "chars": 12000},
    "due_reviews": 5,
    "actions": [
        {"kind": "due", "title": "5 条到期", "detail": "错题和生词排到了今天",
         "href": "#/wrongbook", "label": "去复习"},
        {"kind": "weak", "title": "薄弱点练一道 · 阅读",
         "detail": "掌握度 17%", "href": "#/quiz?focus=阅读", "label": "练这类"},
    ],
    "cet6": [],
}

MODULES = {"schema": 2, "modules": [
    {"id": "ask", "name": "问一问", "icon": "✎", "category": "对话",
     "tagline": "屏幕上的问题，直接问出去", "order": 20, "status": "ready", "home": True},
    {"id": "today", "name": "今日", "icon": "◎", "category": "总览",
     "tagline": "总览", "order": 10, "status": "ready", "home": False},
    {"id": "quiz", "name": "测验", "icon": "?", "category": "学习",
     "tagline": "一次一题", "order": 30, "status": "ready", "home": True},
    {"id": "browser", "name": "浏览器记录", "icon": "◍", "category": "工具",
     "tagline": "记录网页", "order": 40, "status": "ready", "home": True},
    {"id": "future", "name": "待建页", "icon": "·", "category": "其他",
     "tagline": "还没做", "order": 50, "status": "planned", "home": True},
]}

SETTINGS = {"agent": {"ready": True}, "modules": {"browser": False}}
REVIEW = {"reviewed_today": 2, "next_due": "2026-10-26"}


class FakeApi(QtCore.QObject):
    ready = QtCore.Signal()
    failed = QtCore.Signal(str)
    version = "2.20.2"

    def __init__(self, responses=None, errors=None):
        super().__init__()
        self.responses = responses if responses is not None else {
            "/api/overview": OVERVIEW,
            "/api/today": TODAY,
            "/api/modules": MODULES,
            "/api/settings": SETTINGS,
            "/api/review/stats": REVIEW,
        }
        self.errors = errors or {}
        self.started = 0
        self.calls: list[str] = []

    def start(self):
        self.started += 1

    def get(self, path, on_ok, on_err=None):
        self.calls.append(path)
        if path in self.errors:
            if on_err is not None:
                on_err(self.errors[path])
            return
        on_ok(copy.deepcopy(self.responses.get(path, {})))

    def post(self, path, body, on_ok, on_err=None):
        on_ok({})

    def delete(self, path, on_ok, on_err=None):
        on_ok({})


class TestHelpers(unittest.TestCase):
    def test_分钟口径(self):
        self.assertEqual(minutes_parts(30), ("30", "分钟"))
        self.assertEqual(minutes_parts(86), ("1 时 26", "分"))
        self.assertEqual(minutes_parts(120), ("2", "小时"))
        self.assertEqual(minutes_parts(0), ("0", "分钟"))

    def test_字数口径(self):
        self.assertEqual(chars_parts(999), ("999", "字"))
        self.assertEqual(chars_parts(12000), ("1.2", "万字"))

    def test_日期标签(self):
        self.assertEqual(date_label(datetime.date(2026, 10, 24)),
                         "2026 年 10 月 24 日 · 周六")


class TestTodayWindow(unittest.TestCase):
    def setUp(self):
        _app()
        self.api = FakeApi()
        self.opened: list[str] = []
        self.settings_opened = 0
        self.window = TodayWindow(
            self.api,
            navigate=self.opened.append,
            open_settings=self._open_settings,
        )
        self.addCleanup(self.window.deleteLater)
        self.window.load()
        self.api.ready.emit()

    def _open_settings(self):
        self.settings_opened += 1

    def test_Hero_数据(self):
        self.assertEqual(self.window.hero.goal_text.text(), "45 / 100")
        self.assertEqual(self.window.hero.streak_value.text(), "6")
        self.assertEqual(self.window.hero.level_badge.text(), "Lv.2")
        self.assertEqual(self.window.hero.level_title.text(), "布线学徒")
        self.assertEqual(self.window.hero.goal_bar.value(), 450)
        self.assertEqual(self.window.hero.level_bar.value(), 30)
        self.assertEqual(self.window.hero.title.text(), "今天，练一格。")
        self.assertIn("再攒 55 学习点", self.window.hero.goal_note.text())
        self.assertIn("累计 315 点", self.window.hero.level_note.text())

    def test_统计四格(self):
        cells = self.window.stats.cells
        self.assertEqual(cells[0].value.text(), "30")
        self.assertEqual(cells[0].unit.text(), "分钟")
        self.assertEqual(cells[0].note.text(), "切换 4 次")
        self.assertEqual(cells[1].value.text(), "3")
        self.assertEqual(cells[1].note.text(), "最近 10 条里 1 条带图")
        self.assertEqual(cells[2].value.text(), "2")
        self.assertEqual(cells[2].note.text(), "1.2 万字")
        self.assertEqual(cells[3].value.text(), "5")
        self.assertEqual(cells[3].note.text(), "今天已复习 2 条")

    def test_行动卡与跳转(self):
        self.assertEqual(len(self.window.action_cards), 2)
        self.assertEqual(self.window.action_cards[0].number_label.text(), "1")
        self.assertEqual(self.window.action_cards[1].number_label.text(), "2")
        self.window.action_cards[0].clicked.emit()
        self.assertEqual(self.opened, ["#/wrongbook"])

    def test_空行动卡隐藏整段(self):
        api = FakeApi({"/api/overview": OVERVIEW,
                       "/api/today": {**TODAY, "actions": []},
                       "/api/modules": MODULES, "/api/settings": SETTINGS,
                       "/api/review/stats": REVIEW})
        window = TodayWindow(api)
        self.addCleanup(window.deleteLater)
        window.load()
        api.ready.emit()
        self.assertTrue(window.action_section.isHidden())

    def test_插件过滤排序与计数(self):
        names = [card.accessibleName() for card in self.window.plugin_cards]
        self.assertEqual(names, ["问一问", "测验"])
        self.assertEqual(self.window.plugin_cards[0].href, "#/ask")
        self.assertEqual(self.window.plugin_cards[1].href, "#/quiz")
        self.window.plugin_cards[1].clicked.emit()
        self.assertEqual(self.opened, ["#/quiz"])
        texts = [label.text() for label in
                 self.window.plugin_cards[1].findChildren(QtWidgets.QLabel)]
        self.assertIn("1 场测验", texts)

    def test_打开工作台按钮(self):
        self.window.open_button.click()
        self.assertEqual(self.opened, ["#/today"])

    def test_刷新重新拉数(self):
        self.assertEqual(self.api.started, 1)
        self.window.refresh_button.click()
        self.assertEqual(self.api.started, 2)
        self.assertEqual(self.window.status_label.property("state"), "info")
        self.api.ready.emit()
        self.assertEqual(self.window.status_label.property("state"), "ok")

    def test_可选接口失败仍显示主内容(self):
        api = FakeApi(errors={"/api/modules": "后台忙"})
        window = TodayWindow(api)
        self.addCleanup(window.deleteLater)
        window.load()
        api.ready.emit()
        self.assertEqual(window.hero.goal_text.text(), "45 / 100")
        self.assertIn("插件清单", window.status_label.text())
        self.assertFalse(window.plugin_empty.isHidden())

    def test_必需接口失败可重试(self):
        api = FakeApi(errors={"/api/today": "后台忙"})
        window = TodayWindow(api)
        self.addCleanup(window.deleteLater)
        window.load()
        api.ready.emit()
        self.assertIn("今日数据没读出来", window.status_label.text())
        self.assertFalse(window.retry_button.isHidden())
        self.assertTrue(window.refresh_button.isEnabled())

    def test_未配置模型显示提示可进设置(self):
        settings = copy.deepcopy(SETTINGS)
        settings["agent"]["ready"] = False
        api = FakeApi(responses={
            "/api/overview": OVERVIEW, "/api/today": TODAY,
            "/api/modules": MODULES, "/api/settings": settings,
            "/api/review/stats": REVIEW,
        })
        window = TodayWindow(api, open_settings=self._open_settings)
        self.addCleanup(window.deleteLater)
        window.load()
        api.ready.emit()
        self.assertFalse(window.banner.isHidden())
        button = window.banner.findChild(QtWidgets.QPushButton)
        self.assertEqual(button.text(), "去配置")
        button.click()
        self.assertEqual(self.settings_opened, 1)

    def test_响应式列数(self):
        self.window.show()
        _app().processEvents()
        self.assertEqual((self.window._action_cols, self.window._plugin_cols), (1, 2))
        self.window.resize(1000, 700)
        _app().processEvents()
        self.assertEqual((self.window._action_cols, self.window._plugin_cols), (3, 3))
        self.window.resize(800, 600)
        _app().processEvents()
        self.assertEqual((self.window._action_cols, self.window._plugin_cols), (1, 2))

    def test_深色调色板(self):
        palette = self.window.palette()
        self.assertEqual(palette.color(QtGui.QPalette.ColorRole.Window).name(),
                         "#1b1e23")
        self.assertTrue(self.window.styleSheet().strip())


class FakeTodayWindow:
    instances: list["FakeTodayWindow"] = []

    def __init__(self, api, navigate=None, open_settings=None):
        self.api = api
        self.navigate = navigate
        self.open_settings = open_settings
        self.shown = 0
        self.loads = 0
        FakeTodayWindow.instances.append(self)

    def show(self):
        self.shown += 1

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def load(self):
        self.loads += 1


class Host(QtPilotMixin):
    def __init__(self, port):
        self._web_port = port
        self.warnings: list[str] = []
        self.settings_opened = 0

    def _warn(self, message: str) -> None:
        self.warnings.append(message)

    def open_qt_settings(self) -> None:
        self.settings_opened += 1


class TestTodayEntry(unittest.TestCase):
    def setUp(self):
        FakeTodayWindow.instances.clear()
        patches = [
            mock.patch("learnsys.ask.qt.api.ApiClient", lambda port: ("api", port)),
            mock.patch("learnsys.ask.qt.today.TodayWindow", FakeTodayWindow),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_第一次打开建窗口并加载(self):
        host = Host(8765)
        host.open_qt_today()
        self.assertEqual(len(FakeTodayWindow.instances), 1)
        window = FakeTodayWindow.instances[0]
        self.assertEqual(window.shown, 1)
        self.assertEqual(window.loads, 1)
        self.assertEqual(window.api, ("api", 8765))

    def test_重复打开是同一个窗口并重新加载(self):
        host = Host(8765)
        host.open_qt_today()
        first = FakeTodayWindow.instances[0]
        host.open_qt_today()
        self.assertEqual(len(FakeTodayWindow.instances), 1)
        self.assertIs(host._qt_today_window, first)
        self.assertEqual(first.shown, 2)
        self.assertEqual(first.loads, 2)

    def test_服务没起来只提示(self):
        host = Host(0)
        host.open_qt_today()
        self.assertEqual(FakeTodayWindow.instances, [])
        self.assertIn("本地服务", host.warnings[0])

    def test_跳转拼出深链(self):
        with mock.patch("learnsys.ask.workbench.open_or_focus",
                        return_value="ok") as opened:
            self.assertEqual(open_workbench_link(8765, "#/wrongbook"), "ok")
            opened.assert_called_once_with("http://127.0.0.1:8765/#/wrongbook")
            open_workbench_link(8765, "http://example.com/x")
            opened.assert_called_with("http://example.com/x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
