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
from learnsys.ask.qt.today import (AUTO_REFRESH_MS, TodayWindow, chars_parts,  # noqa: E402
                                   date_label, minutes_parts)
from learnsys.ask.qt.today_panels import (AchievementRow, WeekBars,
                                          plain)  # noqa: E402


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
    "week": {"active_days": 4, "minutes": 180, "asks": 12,
             "daily": [
                 {"date": "2026-10-21", "minutes": 0.0, "active": True},
                 {"date": "2026-10-22", "minutes": 60.0, "active": True},
                 {"date": "2026-10-23", "minutes": 0.0, "active": True},
                 {"date": "2026-10-24", "minutes": 120.0, "active": True},
                 {"date": "2026-10-25", "minutes": 0.0, "active": False},
                 {"date": "2026-10-26", "minutes": 0.0, "active": False},
                 {"date": "2026-10-27", "minutes": 0.0, "active": False},
             ]},
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
        self.assertEqual((self.window._action_cols, self.window._plugin_cols), (3, 4))
        self.window.resize(800, 600)
        _app().processEvents()
        self.assertEqual((self.window._action_cols, self.window._plugin_cols), (1, 2))

    def test_深色调色板(self):
        palette = self.window.palette()
        self.assertEqual(palette.color(QtGui.QPalette.ColorRole.Window).name(),
                         "#f3f5f9")
        self.assertTrue(self.window.styleSheet().strip())

    def test_自动刷新定时器随显隐启停(self):
        self.assertEqual(self.window._auto_timer.interval(), AUTO_REFRESH_MS)
        self.assertFalse(self.window._auto_timer.isActive())
        self.window.show()
        _app().processEvents()
        self.assertTrue(self.window._auto_timer.isActive())
        self.window.hide()
        _app().processEvents()
        self.assertFalse(self.window._auto_timer.isActive())

    def test_自动刷新只在可见且空闲时触发(self):
        self.assertEqual(self.api.started, 1)
        self.window._auto_refresh()          # 窗口没显示
        self.assertEqual(self.api.started, 1)
        self.window.show()
        _app().processEvents()
        self.window._auto_refresh()
        self.assertEqual(self.api.started, 2)
        self.window._pending = {"today"}     # 有请求在飞
        self.window._auto_refresh()
        self.assertEqual(self.api.started, 2)
        self.window._pending = set()
        self.window.showMinimized()
        _app().processEvents()
        self.window._auto_refresh()          # 最小化不刷新
        self.assertEqual(self.api.started, 2)

    def test_自动刷新失败保留旧数据(self):
        self.window.show()
        _app().processEvents()
        self.window._auto_refresh()
        self.assertEqual(self.api.started, 2)
        self.api.failed.emit("本地服务没起来")
        self.assertEqual(self.window.hero.goal_text.text(), "45 / 100")
        self.assertIn("自动刷新没连上", self.window.status_label.text())
        self.assertTrue(self.window.retry_button.isHidden())
        self.assertTrue(self.window.refresh_button.isEnabled())


PANEL_OVERVIEW = {
    **copy.deepcopy(OVERVIEW),
    "week": {"active_days": 4, "minutes": 180, "asks": 12,
             "daily": [
                 {"date": "2026-10-21", "minutes": 0.0, "active": True},
                 {"date": "2026-10-22", "minutes": 60.0, "active": True},
                 {"date": "2026-10-23", "minutes": 0.0, "active": True},
                 {"date": "2026-10-24", "minutes": 120.0, "active": True},
                 {"date": "2026-10-25", "minutes": 0.0, "active": False},
                 {"date": "2026-10-26", "minutes": 0.0, "active": False},
                 {"date": "2026-10-27", "minutes": 0.0, "active": False},
             ]},
    "achievements": [
        {"id": "first_ask", "name": "第一问", "desc": "问出第一个问题",
         "value": 1, "target": 1, "earned": True},
        {"id": "asks_50", "name": "五十问", "desc": "累计问过 50 个问题",
         "value": 3, "target": 50, "earned": False},
        {"id": "streak_3", "name": "连续三天", "desc": "连续 3 天都有学习记录",
         "value": 3, "target": 3, "earned": True},
        {"id": "star_10", "name": "错题十道", "desc": "错题本收了 10 道题",
         "value": 0, "target": 10, "earned": False},
    ],
}

PANEL_TODAY = {
    "date": "2026-10-24",
    "focus": {"minutes": 45, "switches": 3,
              "apps": [["VS Code", 30.4], ["Edge", 14.6]]},
    "asks": [
        {"ts": "2026-10-24 14:03:12", "question": "什么是 RBAC",
         "answer": "## 标题\n\n**权限** `role` [文档](https://x)\n"
                   "```py\nprint(1)\n```",
         "kind": "text", "conversation_id": 42},
        {"ts": "2026-10-24 09:01:00", "question": "图上是什么",
         "answer": "一张图", "kind": "image", "conversation_id": None},
    ],
    "ask_count": 2,
    "transcripts": {"count": 0, "chars": 0},
    "due_reviews": 0,
    "actions": [],
    "cet6": [{"paper": "强化卷三", "section": "Section C",
              "item": "Recording 3", "count": 5, "paper_id": "paper-3"}],
}

PANEL_CONVERSATIONS = {"items": [{"id": 7, "messages": 3},
                                 {"id": 8, "messages": 5}]}


def _panel_api(**overrides):
    responses = {
        "/api/overview": PANEL_OVERVIEW,
        "/api/today": PANEL_TODAY,
        "/api/modules": MODULES,
        "/api/settings": SETTINGS,
        "/api/review/stats": REVIEW,
        "/api/conversations?limit=8": PANEL_CONVERSATIONS,
    }
    responses.update(overrides)
    return FakeApi(responses=responses)


class TestTodayPanels(unittest.TestCase):
    """R5：时间线 / 本周 / 专注 / 六级 / 成就 / 快捷入口。"""

    def _window(self, navigate=None, **overrides):
        _app()
        api = _panel_api(**overrides)
        opened = navigate if navigate is not None else []
        window = TodayWindow(api, navigate=opened.append)
        self.addCleanup(window.deleteLater)
        window.load()
        api.ready.emit()
        return window, opened

    def test_纯文本摘要与_Web_同口径(self):
        raw = "## 标题\n\n**权限** `role` [文档](https://x)\n```py\nprint(1)\n```"
        self.assertEqual(plain(raw), "标题 权限 role 文档 ［代码］")
        self.assertEqual(plain("短文本"), "短文本")
        long = plain("字" * 200)
        self.assertEqual(len(long), 181)
        self.assertTrue(long.endswith("…"))

    def test_时间线渲染(self):
        window, _ = self._window()
        self.assertEqual(window.timeline.count.text(), "最近 2 条")
        self.assertEqual(len(window.timeline.items), 2)
        first, second = window.timeline.items
        self.assertEqual(first.time.text(), "14:03")
        self.assertEqual(first.question.text(), "什么是 RBAC")
        self.assertEqual(first.answer.text(), "标题 权限 role 文档 ［代码］")
        self.assertTrue(first.tag.isHidden())
        self.assertFalse(second.tag.isHidden())
        self.assertEqual(second.question.text(), "图上是什么")
        self.assertTrue(window.timeline.empty.isHidden())

    def test_时间线空状态(self):
        window, _ = self._window(**{"/api/today": {**PANEL_TODAY, "asks": []}})
        self.assertEqual(window.timeline.count.text(), "")
        self.assertFalse(window.timeline.empty.isHidden())
        self.assertEqual(window.timeline.items, [])

    def test_时间线点击跳转与快捷栏提示(self):
        window, opened = self._window()
        window.timeline.items[0].clicked.emit()
        self.assertEqual(opened, ["#/ask/42"])
        window.timeline.items[1].clicked.emit()
        self.assertEqual(opened, ["#/ask/42"])
        self.assertIn("快捷栏", window.status_label.text())

    def test_本周面板(self):
        window, _ = self._window()
        bars = window.week_panel.findChild(WeekBars)
        self.assertIsNotNone(bars)
        self.assertEqual(len(bars.days), 7)
        self.assertEqual(bars.days[3]["minutes"], 120.0)
        note = [label.text() for label in window.week_panel.findChildren(
            QtWidgets.QLabel, "PanelNote")]
        self.assertEqual(note, ["共 3 小时 · 活跃 4 / 7 天"])

    def test_专注明细(self):
        window, _ = self._window()
        values = [row.value.text() for row in window.focus_panel.rows]
        self.assertEqual(values, ["45 分钟", "3 次", "30 分钟", "15 分钟"])
        labels = [row.label.text() for row in window.focus_panel.rows]
        self.assertEqual(labels[2:], ["VS Code", "Edge"])
        self.assertEqual(window.focus_panel.findChildren(
            QtWidgets.QLabel, "PanelNote"), [])

    def test_专注空状态提示(self):
        today = {**PANEL_TODAY,
                 "focus": {"minutes": 0, "switches": 0, "apps": []}}
        window, _ = self._window(**{"/api/today": today})
        notes = window.focus_panel.findChildren(QtWidgets.QLabel, "PanelNote")
        self.assertEqual(len(notes), 1)
        self.assertIn("开始录像", notes[0].text())

    def test_六级断点面板与跳转(self):
        window, opened = self._window()
        self.assertFalse(window.cet6_panel.isHidden())
        self.assertEqual(len(window.cet6_panel.rows), 1)
        row = window.cet6_panel.rows[0]
        self.assertEqual(row.label.text(), "强化卷三 · Section C · Recording 3")
        self.assertEqual(row.value.text(), "5 个断点")
        row.clicked.emit()
        self.assertEqual(opened, ["#/cet6?paper=paper-3"])

    def test_六级无数据时隐藏(self):
        window, _ = self._window(
            **{"/api/today": {**PANEL_TODAY, "cet6": []}})
        self.assertTrue(window.cet6_panel.isHidden())

    def test_成就排序与计数(self):
        window, _ = self._window()
        self.assertEqual(window.ach_panel.hint.text(), "2 / 4")
        rows = window.ach_panel.findChildren(AchievementRow)
        self.assertEqual([row.name.text() for row in rows],
                         ["第一问", "连续三天", "五十问", "错题十道"])
        self.assertTrue(rows[0].earned)
        self.assertFalse(rows[2].earned)
        self.assertEqual(rows[0].progress.text(), "1/1")
        self.assertEqual(rows[2].progress.text(), "3/50")

    def test_成就最多显示八条(self):
        items = [{"id": f"a{i}", "name": f"成就{i}", "desc": "",
                  "value": i, "target": 10, "earned": i % 2 == 0}
                 for i in range(12)]
        window, _ = self._window(
            **{"/api/overview": {**PANEL_OVERVIEW, "achievements": items}})
        rows = window.ach_panel.findChildren(AchievementRow)
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(row.earned for row in rows[:6]))

    def test_快捷入口跳转(self):
        window, opened = self._window()
        window.ask_shortcut.clicked.emit()
        window.netlab_shortcut.clicked.emit()
        self.assertEqual(opened, ["#/ask", "#/netlab"])

    def test_继续最近会话(self):
        window, opened = self._window()
        self.assertEqual(window._continue_conv, "7")
        window.continue_shortcut.clicked.emit()
        self.assertEqual(opened, ["#/ask/7"])

    def test_没有会话时提示(self):
        window, opened = self._window(
            **{"/api/conversations?limit=8": {"items": []}})
        window.continue_shortcut.clicked.emit()
        self.assertIn("还没有会话", window.status_label.text())
        self.assertEqual(opened, ["#/ask"])

    def test_底栏响应式堆叠(self):
        window, _ = self._window()
        window.show()
        _app().processEvents()
        self.assertTrue(window._bottom_stacked)      # offscreen 工作区小，先堆叠
        index = window.bottom_grid.indexOf(window.side)
        self.assertEqual(window.bottom_grid.getItemPosition(index)[:2], (1, 0))
        window.resize(1000, 700)
        _app().processEvents()
        self.assertFalse(window._bottom_stacked)
        index = window.bottom_grid.indexOf(window.side)
        self.assertEqual(window.bottom_grid.getItemPosition(index)[:2], (0, 1))
        window.resize(800, 600)
        _app().processEvents()
        self.assertTrue(window._bottom_stacked)
        index = window.bottom_grid.indexOf(window.side)
        self.assertEqual(window.bottom_grid.getItemPosition(index)[:2], (1, 0))

    def test_缺字段不崩(self):
        today = {"asks": [{"question": "只有问题"}]}
        overview = {"today": {}, "total": {}, "week": {}, "achievements": []}
        window, _ = self._window(**{"/api/today": today,
                                    "/api/overview": overview})
        self.assertEqual(len(window.timeline.items), 1)
        bars = window.week_panel.findChild(WeekBars)
        self.assertIsNotNone(bars)
        self.assertEqual(bars.days, [])
        self.assertTrue(window.cet6_panel.isHidden())
        self.assertEqual(window.ach_panel.hint.text(), "0 / 0")


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

    def test_没有窗口时新开带深链的窗口(self):
        opened = mock.Mock(return_value="ok")
        self.assertEqual(
            open_workbench_link(8765, "#/wrongbook", has_window=lambda: False,
                                open_url=opened),
            "ok",
        )
        opened.assert_called_once_with("http://127.0.0.1:8765/#/wrongbook")
        opened.reset_mock()
        open_workbench_link(8765, "http://example.com/x", has_window=lambda: False,
                            open_url=opened)
        opened.assert_called_once_with("http://example.com/x")

    def test_已有窗口先写队列再聚焦(self):
        calls: list[tuple] = []
        result = open_workbench_link(
            8765, "#/quiz?focus=词汇",
            has_window=lambda: True,
            post=lambda port, href: calls.append(("post", port, href)) or True,
            focus=lambda: calls.append(("focus",)),
            open_url=lambda url: calls.append(("open", url)),
        )
        self.assertEqual(result, "已聚焦现有学习工作台")
        self.assertEqual(calls, [("post", 8765, "#/quiz?focus=词汇"), ("focus",)])

    def test_已有窗口但队列写失败仍然聚焦(self):
        focused = mock.Mock()
        result = open_workbench_link(
            8765, "#/today", has_window=lambda: True,
            post=lambda port, href: False, focus=focused,
            open_url=lambda url: self.fail("有窗口时不该新开"),
        )
        self.assertIn("跳转请求没发出去", result)
        focused.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
