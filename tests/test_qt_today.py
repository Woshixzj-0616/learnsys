# -*- coding: utf-8 -*-
"""今日页 Qt：结构、数据、场景切换、刷新与入口。"""
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

from learnsys import config  # noqa: E402
from learnsys.ask.desktop.qt_pilot import QtPilotMixin, open_workbench_link  # noqa: E402
from learnsys.ask.qt import tokens as token_source  # noqa: E402
from learnsys.ask.qt.today import AUTO_REFRESH_MS, TodayWindow, date_label  # noqa: E402
from learnsys.ask.qt.today_panels import WeekBars, plain  # noqa: E402
from learnsys.ask.qt.today_widgets import (FactsStrip, chars_parts,  # noqa: E402
                                           minutes_parts)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


OVERVIEW = {
    "date": "2026-10-24",
    "name": "智坚",
    "today": {"xp": 45, "goal": 100, "percent": 45.0, "asks": 3, "minutes": 30,
              "study_minutes": 45.0, "study_measured": 30.0,
              "study_estimated": 15.0,
              "study_breakdown": {"focus": 30.0, "cet6": 15.0},
              "activity": {"breakpoints": 4, "asks": 3},
              "goal_tasks": [
                  {"id": "listen", "title": "精听 · 测试卷 / Section C",
                   "detail": "今天 2 个不同句子", "minutes": 25, "done": False,
                   "label": "去精听", "href": "#/cet6"},
                  {"id": "output", "title": "写作 · 练习",
                   "detail": "写完并提交", "minutes": 30, "done": True,
                   "label": "去做", "href": "#/cet6?tab=writing"},
                  {"id": "report", "title": "复盘今天",
                   "detail": "让 AI 读一遍今天的记录", "minutes": 10, "done": False,
                   "label": "去复盘", "href": "#/review"},
              ],
              "goal_done": 1, "goal_total": 3, "goal_tier": "floor",
              "goal_budget_minutes": 65,
              "cet6": 2, "netlab": 1, "review": 1, "quiz": 1},
    "total": {"xp": 315, "level": 2, "title": "布线学徒", "into": 15,
              "need": 500, "percent": 3.0},
    "streak": 6,
    "week": {"active_days": 4, "minutes": 180, "study_minutes": 180,
             "achieved_days": 1, "goal_days": 5, "asks": 12,
             "daily": [
                 {"date": "2026-10-21", "minutes": 0.0, "study_minutes": 0.0,
                  "goal_done": 0, "goal_total": 3, "goal_achieved": False,
                  "active": True},
                 {"date": "2026-10-22", "minutes": 60.0, "study_minutes": 60.0,
                  "goal_done": 2, "goal_total": 3, "goal_achieved": False,
                  "active": True},
                 {"date": "2026-10-23", "minutes": 0.0, "study_minutes": 0.0,
                  "goal_done": 0, "goal_total": 3, "goal_achieved": False,
                  "active": True},
                 {"date": "2026-10-24", "minutes": 120.0, "study_minutes": 120.0,
                  "goal_done": 3, "goal_total": 3, "goal_achieved": True,
                  "active": True},
                 {"date": "2026-10-25", "minutes": 0.0, "study_minutes": 0.0,
                  "goal_done": 0, "goal_total": 3, "goal_achieved": False,
                  "active": False},
                 {"date": "2026-10-26", "minutes": 0.0, "study_minutes": 0.0,
                  "goal_done": 0, "goal_total": 3, "goal_achieved": False,
                  "active": False},
                 {"date": "2026-10-27", "minutes": 0.0, "study_minutes": 0.0,
                  "goal_done": 0, "goal_total": 3, "goal_achieved": False,
                  "active": False},
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

TODAY = {
    "date": "2026-10-24",
    "study_minutes": 45.0,
    "study_measured": 30.0,
    "study_estimated": 15.0,
    "activity": {"breakpoints": 4, "asks": 3, "trains": 0},
    "focus": {"minutes": 30, "switches": 4, "apps": []},
    "asks": [
        {"ts": "2026-10-24 20:10:00", "kind": "text",
         "question": "什么是 RBAC",
         "answer": "## 标题\n\n**权限** `role` [文档](https://x)\n```py\nprint(1)\n```",
         "conversation_id": 42},
        {"ts": "2026-10-24 19:01:00", "kind": "image",
         "question": "图上是什么", "answer": "一张图",
         "conversation_id": None},
        {"ts": "2026-10-24 09:01:00", "kind": "text",
         "question": "#include<iostream>\nint main() { return 0; }\n",
         "answer": "这里把赋值写成了比较", "conversation_id": 43},
    ],
    "ask_count": 3,
    "transcripts": {"count": 2, "chars": 12000},
    "due_reviews": 5,
    "actions": [
        {"kind": "cet6", "title": "接着昨天的听力断点",
         "detail": "强化卷三（5 个断点）", "href": "#/cet6?paper=paper-3",
         "label": "回到断点"},
        {"kind": "train", "title": "六级训练 · 大学生该不该做兼职",
         "detail": "观点论证 · 30 分钟", "href": "#/cet6?tab=writing",
         "label": "开始写作"},
        {"kind": "weak", "title": "薄弱点练一道 · 阅读",
         "detail": "掌握度 17%", "href": "#/quiz?focus=阅读", "label": "练这类"},
    ],
    "cet6": [
        {"paper": "强化卷三", "section": "Section C", "item": "Recording 3",
         "count": 5, "paper_id": "paper-3", "last": "2026-10-24 09:38:00"},
    ],
}

HOME = {
    "date": "2026-10-24",
    "learning": {
        "href": "#/review", "done": 1, "total": 3, "due_reviews": 5,
        "recent_wrong": [{"question": "二叉树遍历怎么写"}],
    },
    "work": {
        "href": "#/agents", "running": 1, "queued": 2,
        "projects": [{"name": "学习工作台", "next_step": "完成 P27.2"}],
        "next_step": "完成 P27.2",
    },
    "life": {
        "href": "#/life", "card_count": 3, "unread_count": 2,
        "subscription_count": 3, "event_count": 2,
        "reminders": ["订阅：AI 新闻"],
    },
}

BRIEFING = {
    "day": "2026-10-24",
    "status": "ready",
    "item_count": 2,
    "created_at": "2026-10-24 20:36:03",
    "updated_at": "2026-10-24 20:36:03",
    "source_ok": 14,
    "source_total": 14,
    "items": [
        {"category_label": "能源/航天", "title": "商业火箭企业总部落地上海",
         "title_zh": "", "summary": "上海箭元航天科技有限公司正式落地青浦。",
         "source": "IT之家", "published_at": "2026-10-24 19:30"},
        {"category_label": "时政", "title": "中国再为 8 位烈士确认身份",
         "title_zh": "", "summary": "退役军人事务部举行发布会。",
         "source": "中国新闻网", "published_at": "2026-10-24 19:26"},
    ],
}

SETTINGS = {"agent": {"ready": True}, "briefing": {"enabled": True},
            "modules": {}}


class FakeApi(QtCore.QObject):
    ready = QtCore.Signal()
    failed = QtCore.Signal(str)
    version = "2.20.2"

    def __init__(self, responses=None, errors=None):
        super().__init__()
        self.responses = responses if responses is not None else {
            "/api/overview": OVERVIEW,
            "/api/today": TODAY,
            "/api/settings": SETTINGS,
            "/api/briefing/today": BRIEFING,
            "/api/home": HOME,
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


def _window(responses=None, errors=None, **kwargs):
    _app()
    api = FakeApi(responses=responses, errors=errors)
    opened: list[str] = []
    window = TodayWindow(api, navigate=opened.append, **kwargs)
    window.load()
    api.ready.emit()
    return window, opened


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
        self.window, self.opened = _window()
        self.addCleanup(self.window.deleteLater)

    def test_Hero_数据(self):
        hero = self.window.hero
        self.assertTrue(hero.title.text().endswith("，智坚"))
        self.assertEqual(hero.level_chip.text(), "Lv.2 · 布线学徒")
        self.assertEqual(hero.streak_chip.text(), "连续 6 天")
        self.assertEqual(hero.state.text(), "完成 1 件 · 再做一件就达标")
        self.assertEqual(hero.ring.label, "1 / 3")
        self.assertAlmostEqual(hero.ring.percent, 100 / 3, places=2)
        self.assertEqual(len(hero.tasks), 3)
        self.assertEqual(hero.tasks[0].check.text(), "○")
        self.assertEqual(hero.tasks[1].check.text(), "√")
        self.assertIn("精听", hero.tasks[0].title.text())
        self.assertEqual(hero.tasks[0].minutes.text(), "25 分钟")

    def test_Hero_任务与提问跳转(self):
        self.window.hero.tasks[0].clicked.emit()
        self.window.hero.ask.clicked.emit()
        self.assertEqual(self.opened, ["#/cet6", "#/ask"])

    def test_三域卡内容与跳转(self):
        grid = self.window.domains
        self.assertEqual(list(grid.cards), ["learn", "work", "life"])
        learn = grid.cards["learn"]
        work = grid.cards["work"]
        life = grid.cards["life"]
        self.assertEqual(learn.title.text(), "今日 1/3 · 到期复习 5")
        self.assertIn("二叉树遍历怎么写", learn.sub.text())
        self.assertEqual(work.title.text(), "进行中 1 · 待排队 2")
        self.assertIn("完成 P27.2", work.sub.text())
        self.assertEqual(life.title.text(), "今日卡片 3 · 未读 2")
        self.assertIn("AI 新闻", life.sub.text())
        learn.clicked.emit()
        work.clicked.emit()
        life.clicked.emit()
        self.assertEqual(self.opened, ["#/review", "#/agents", "#/life"])

    def test_三域卡无数据仍保留入口(self):
        window, opened = _window(responses={
            "/api/overview": OVERVIEW, "/api/today": TODAY,
            "/api/settings": SETTINGS, "/api/briefing/today": BRIEFING,
        })
        self.addCleanup(window.deleteLater)
        learn = window.domains.cards["learn"]
        self.assertEqual(learn.title.text(), "今日 0/3 · 到期复习 0")
        self.assertIn("暂无", learn.sub.text())
        learn.clicked.emit()
        self.assertEqual(opened, ["#/cet6"])

    def test_三域入口失败不挡主内容(self):
        window, _ = _window(errors={"/api/home": "后台忙"})
        self.addCleanup(window.deleteLater)
        self.assertTrue(window.hero.title.text())
        self.assertIn("三域入口", window.status_label.text())
        self.assertEqual(window.domains.cards["work"].title.text(),
                         "进行中 0 · 待排队 0")

    def test_简报横条(self):
        band = self.window.briefing
        self.assertFalse(band.isHidden())
        self.assertIn("10 月 24 日", band.eyebrow.text())
        self.assertEqual(band.title.text(), "今天值得知道的 2 件事")
        self.assertIn("已生成 20:36", band.meta.text())
        self.assertIn("14 / 14 源", band.meta.text())
        self.assertEqual(len(band.rows), 1)
        self.assertIn("商业火箭", band.lead.title.text())
        band.lead.clicked.emit()
        self.assertEqual(self.opened, ["#/briefing"])

    def test_简报关闭时不显示(self):
        settings = copy.deepcopy(SETTINGS)
        settings["briefing"]["enabled"] = False
        window, _ = _window(responses={
            "/api/overview": OVERVIEW, "/api/today": TODAY,
            "/api/settings": settings, "/api/briefing/today": BRIEFING,
        })
        self.addCleanup(window.deleteLater)
        self.assertTrue(window.briefing.isHidden())

    def test_简报空态(self):
        empty = {**BRIEFING, "status": "missing", "item_count": 0, "items": []}
        window, _ = _window(responses={
            "/api/overview": OVERVIEW, "/api/today": TODAY,
            "/api/settings": SETTINGS, "/api/briefing/today": empty,
        })
        self.addCleanup(window.deleteLater)
        self.assertFalse(window.briefing.isHidden())
        self.assertEqual(window.briefing.title.text(), "今天的简报还没生成")
        self.assertFalse(window.briefing.empty.isHidden())

    def test_接着上次与备选行动去重(self):
        card = self.window.continue_card
        self.assertEqual(card.title.text(), "强化卷三")
        self.assertIn("Section C", card.sub.text())
        self.assertEqual(card.count.text(), "5 处断点")
        self.assertEqual(card.last.text(), "最近 09:38")
        self.assertEqual(card.state.text(), "今天还没练")
        self.assertEqual(len(card.alts), 2)
        self.assertIn("兼职", card.alts[0].findChild(
            QtWidgets.QLabel, "AltTitle").text())
        card.alts[0].clicked.emit()
        card.button.click()
        self.assertEqual(self.opened, ["#/cet6?tab=writing",
                                       "#/cet6?paper=paper-3"])

    def test_精听达标文案(self):
        overview = copy.deepcopy(OVERVIEW)
        overview["today"]["goal_tasks"][0]["done"] = True
        window, _ = _window(responses={
            "/api/overview": overview, "/api/today": TODAY,
            "/api/settings": SETTINGS, "/api/briefing/today": BRIEFING,
        })
        self.addCleanup(window.deleteLater)
        self.assertEqual(window.continue_card.state.text(), "今天精听已达标")

    def test_时间线分组与内容(self):
        timeline = self.window.timeline
        self.assertEqual(timeline.count.text(), "3 条记录")
        self.assertEqual(len(timeline.items), 3)
        labels = [label.text() for label in timeline.findChildren(
            QtWidgets.QLabel, "TimelineGroupLabel")]
        self.assertEqual(labels, ["晚上", "上午"])
        first = timeline.items[0]
        self.assertEqual(first.time.text(), "20:10")
        self.assertEqual(first.question.text(), "什么是 RBAC")
        self.assertEqual(first.answer.text(), "标题 权限 role 文档 ［代码］")
        code = timeline.items[2]
        self.assertIn("粘贴了一段 C++ 代码", code.question.text())
        self.assertEqual(code.tag.text(), "代码")
        self.assertFalse(code.tag.isHidden())

    def test_时间线最多六条(self):
        asks = [{"ts": f"2026-10-24 {18 + i // 60:02d}:{i % 60:02d}:00",
                 "question": f"问题{i}", "answer": "答", "kind": "text",
                 "conversation_id": i} for i in range(8)]
        window, _ = _window(responses={
            "/api/overview": OVERVIEW, "/api/today": {**TODAY, "asks": asks},
            "/api/settings": SETTINGS, "/api/briefing/today": BRIEFING,
        })
        self.addCleanup(window.deleteLater)
        self.assertEqual(len(window.timeline.items), 6)
        self.assertEqual(window.timeline.count.text(), "8 条记录 · 最近 6 条")

    def test_时间线点击与快捷栏提示(self):
        self.window.timeline.items[0].clicked.emit()
        self.assertEqual(self.opened, ["#/ask/42"])
        self.window.timeline.items[1].clicked.emit()
        self.assertIn("快捷栏", self.window.status_label.text())

    def test_本周与今天一行(self):
        window = self.window
        self.assertEqual(window.week_panel.hint.text(), "达标 1 / 5 天")
        bars = window.week_panel.findChild(WeekBars)
        self.assertIsNotNone(bars)
        self.assertEqual(len(bars.days), 7)
        notes = [label.text() for label in window.week_panel.findChildren(
            QtWidgets.QLabel, "PanelNote")]
        self.assertEqual(notes, ["共 3 小时 · 活跃 4 / 7 天"])
        facts = window.week_panel.findChild(FactsStrip)
        values = [value.text() for value, _ in facts.cells]
        labels = [label.text() for _, label in facts.cells]
        self.assertEqual(values, ["3", "5", "1", "30 分钟"])
        self.assertEqual(labels, ["问答", "听力断点", "训练", "实测专注"])

    def test_成就默认折叠(self):
        card = self.window.ach_card
        self.assertEqual(card.summary.text(),
                         "2 / 4 · 下一项 五十问 3/50")
        self.assertEqual(len(card.items), 4)
        self.assertTrue(card.body.isHidden())
        card.header.clicked.emit()
        self.assertFalse(card.body.isHidden())
        self.assertEqual(card.chev.text(), "⌄")
        card.header.clicked.emit()
        self.assertTrue(card.body.isHidden())
        self.assertEqual([row.name.text() for row in card.items],
                         ["第一问", "连续三天", "五十问", "错题十道"])

    def test_学习与工作场景(self):
        self.assertFalse(self.window.continue_card.isHidden())
        self.assertTrue(self.window.work_card.isHidden())
        self.window.scene_work.click()
        self.assertEqual(self.window._scene, "work")
        self.assertTrue(self.window.continue_card.isHidden())
        self.assertFalse(self.window.work_card.isHidden())
        self.window.scene_study.click()
        self.assertFalse(self.window.continue_card.isHidden())
        self.assertTrue(self.window.work_card.isHidden())

    def test_底栏响应式堆叠(self):
        window = self.window
        window.show()
        _app().processEvents()
        self.assertTrue(window._bottom_stacked)
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

    def test_打开工作台按钮(self):
        self.window.open_button.click()
        self.assertEqual(self.opened, ["#/today"])

    def test_刷新重新拉数(self):
        api = self.window.api
        self.assertEqual(api.started, 1)
        self.window.refresh_button.click()
        self.assertEqual(api.started, 2)
        api.ready.emit()
        self.assertEqual(self.window.status_label.property("state"), "ok")

    def test_可选接口失败仍显示主内容(self):
        window, _ = _window(errors={"/api/settings": "后台忙"})
        self.addCleanup(window.deleteLater)
        self.assertTrue(window.hero.title.text())
        self.assertIn("设置", window.status_label.text())

    def test_必需接口失败可重试(self):
        window, _ = _window(errors={"/api/today": "后台忙"})
        self.addCleanup(window.deleteLater)
        self.assertIn("今日数据没读出来", window.status_label.text())
        self.assertFalse(window.retry_button.isHidden())
        self.assertTrue(window.refresh_button.isEnabled())

    def test_未配置模型显示提示可进设置(self):
        settings = copy.deepcopy(SETTINGS)
        settings["agent"]["ready"] = False
        opened_settings = []
        window, _ = _window(
            responses={"/api/overview": OVERVIEW, "/api/today": TODAY,
                       "/api/settings": settings, "/api/briefing/today": BRIEFING},
            open_settings=lambda: opened_settings.append(1))
        self.addCleanup(window.deleteLater)
        self.assertFalse(window.banner.isHidden())
        button = window.banner.findChild(QtWidgets.QPushButton)
        self.assertEqual(button.text(), "去配置")
        button.click()
        self.assertEqual(opened_settings, [1])

    def test_默认深色调色板(self):
        values = token_source.read_web_tokens(mood=config.DEFAULT_MOOD)
        palette = self.window.palette()
        self.assertEqual(palette.color(QtGui.QPalette.ColorRole.Window).name(),
                         values["--bg"])
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
        api = self.window.api
        self.assertEqual(api.started, 1)
        self.window._auto_refresh()
        self.assertEqual(api.started, 1)
        self.window.show()
        _app().processEvents()
        self.window._auto_refresh()
        self.assertEqual(api.started, 2)
        self.window._pending = {"today"}
        self.window._auto_refresh()
        self.assertEqual(api.started, 2)
        self.window._pending = set()
        self.window.showMinimized()
        _app().processEvents()
        self.window._auto_refresh()
        self.assertEqual(api.started, 2)

    def test_自动刷新失败保留旧数据(self):
        self.window.show()
        _app().processEvents()
        self.window._auto_refresh()
        self.window.api.failed.emit("本地服务没起来")
        self.assertTrue(self.window.hero.title.text())
        self.assertIn("自动刷新没连上", self.window.status_label.text())
        self.assertTrue(self.window.retry_button.isHidden())


class TestTodayPanels(unittest.TestCase):
    def test_纯文本摘要与_Web_同口径(self):
        raw = "## 标题\n\n**权限** `role` [文档](https://x)\n```py\nprint(1)\n```"
        self.assertEqual(plain(raw), "标题 权限 role 文档 ［代码］")
        self.assertEqual(plain("短文本"), "短文本")
        long = plain("字" * 200)
        self.assertEqual(len(long), 181)
        self.assertTrue(long.endswith("…"))

    def test_缺字段不崩(self):
        window, _ = _window(responses={
            "/api/overview": {"today": {}, "total": {}, "week": {},
                              "achievements": []},
            "/api/today": {"asks": [{"question": "只有问题"}]},
            "/api/settings": SETTINGS, "/api/briefing/today": {},
        })
        self.addCleanup(window.deleteLater)
        self.assertEqual(len(window.timeline.items), 1)
        bars = window.week_panel.findChild(WeekBars)
        self.assertIsNotNone(bars)
        self.assertEqual(bars.days, [])
        self.assertEqual(window.ach_card.summary.text(), "0 / 0")


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
