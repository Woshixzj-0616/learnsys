"""今日页（Qt）。

数据全部来自现有 `/api/*`；本页只负责展示与跳转。
结构对齐 Web 今日页（2026-10-28 改版）：Hero → 简报横条 → 接着上次 + 问答轨道 / 本周 + 成就。
颜色/字号/圆角沿用 `style.py`（令牌来自 `web/css/tokens.css`）。
"""
from __future__ import annotations

import datetime

from PySide6 import QtCore, QtWidgets

from learnsys import product

from . import style
from . import tokens as token_source
from .today_bottom import TodayBottomMixin
from .today_briefing import BriefingBand
from .today_widgets import HeroCard, OnboardingBanner
from .widgets import StatusLabel

TODAY_SIZE = (1040, 700)
TODAY_MIN = (760, 560)
CONTENT_MAX = 1040
AUTO_REFRESH_MS = 60_000   # 今日页可见时每分钟静默拉一次，窗口隐藏就停


def date_label(now: datetime.date | None = None) -> str:
    now = now or datetime.date.today()
    week = "日一二三四五六"[now.isoweekday() % 7]
    return f"{now.year} 年 {now.month} 月 {now.day} 日 · 周{week}"


class TodayWindow(TodayBottomMixin, QtWidgets.QDialog):
    """非模态今日页；每次打开/刷新都重新拉一次数据。"""

    def __init__(self, api, navigate=None, open_settings=None,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.api = api
        if isinstance(api, QtCore.QObject):
            api.setParent(self)
        self._navigate = navigate or (lambda _href: None)
        self._open_settings = open_settings

        self._base_title = f"今日（Qt 试点）· {product.PRODUCT_NAME}"
        self.setObjectName("TodayWindow")
        self.setWindowTitle(self._base_title)
        self.tokens = style.apply_theme(self)
        self.resize(*style.fit_size(TODAY_SIZE))
        self.setMinimumSize(*TODAY_MIN)

        self._data: dict[str, dict] = {}
        self._errors: dict[str, str] = {}
        self._pending: set[str] = set()
        self._required_failed = False
        self._bottom_stacked = False
        self._scene = "study"          # 学习 / 工作：只换左侧入口
        self._silent = False

        self._auto_timer = QtCore.QTimer(self)
        self._auto_timer.setInterval(AUTO_REFRESH_MS)
        self._auto_timer.timeout.connect(self._auto_refresh)

        self._build()
        self.api.ready.connect(self._on_ready)
        self.api.failed.connect(self._on_failed)

    # ---- 骨架 ----

    def _build(self) -> None:
        outer = QtWidgets.QGridLayout(self)
        pad = int(token_source.px(self.tokens, "--s5", 24))
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(0)

        column_widget = QtWidgets.QWidget()
        column_widget.setObjectName("TodayColumn")
        column_widget.setMaximumWidth(CONTENT_MAX)
        column_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                    QtWidgets.QSizePolicy.Policy.Expanding)
        column = QtWidgets.QVBoxLayout(column_widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        outer.addWidget(column_widget, 0, 1)
        outer.setColumnStretch(0, 1)
        outer.setColumnStretch(1, 100)
        outer.setColumnStretch(2, 1)
        outer.setRowStretch(0, 1)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(12)
        title = QtWidgets.QLabel("今日")
        title.setObjectName("TodayTitle")
        date = QtWidgets.QLabel(date_label())
        date.setObjectName("TodayDate")
        head.addWidget(title)
        head.addWidget(date)
        head.addStretch(1)
        self.scene_study = QtWidgets.QPushButton("学习")
        self.scene_work = QtWidgets.QPushButton("工作")
        for button in (self.scene_study, self.scene_work):
            button.setToolTip("切换今日页的入口")
        self.scene_study.clicked.connect(lambda: self._set_scene("study"))
        self.scene_work.clicked.connect(lambda: self._set_scene("work"))
        head.addWidget(self.scene_study)
        head.addWidget(self.scene_work)
        head.addSpacing(6)
        self.refresh_button = QtWidgets.QPushButton("刷新")
        self.refresh_button.clicked.connect(self.load)
        self.open_button = QtWidgets.QPushButton("打开工作台")
        self.open_button.setObjectName("Primary")
        self.open_button.clicked.connect(lambda: self._navigate("#/today"))
        head.addWidget(self.refresh_button)
        head.addWidget(self.open_button)
        column.addLayout(head)
        self._paint_scene_buttons()

        status_row = QtWidgets.QHBoxLayout()
        self.status_label = StatusLabel("正在连接后台…")
        self.retry_button = QtWidgets.QPushButton("重试")
        self.retry_button.clicked.connect(self.load)
        self.retry_button.hide()
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.retry_button)
        column.addLayout(status_row)

        self.banner = OnboardingBanner()
        self.banner.configure.connect(self._configure)
        column.addWidget(self.banner)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QtWidgets.QWidget()
        content.setObjectName("TodayContent")
        body = QtWidgets.QVBoxLayout(content)
        body.setContentsMargins(0, 0, 6, int(token_source.px(self.tokens, "--s5", 24)))
        body.setSpacing(int(token_source.px(self.tokens, "--s5", 24)))

        self.hero = HeroCard(self.tokens, self._navigate)
        body.addWidget(self.hero)

        self.briefing = BriefingBand(self._navigate)
        body.addWidget(self.briefing)

        self._build_bottom(body)
        body.addStretch(1)
        scroll.setWidget(content)
        column.addWidget(scroll, 1)

    def _paint_scene_buttons(self) -> None:
        for button, key in ((self.scene_study, "study"),
                            (self.scene_work, "work")):
            name = "Primary" if self._scene == key else ""
            if button.objectName() == name:
                continue
            button.setObjectName(name)
            button.style().unpolish(button)
            button.style().polish(button)

    def _set_scene(self, scene: str) -> None:
        scene = "work" if scene == "work" else "study"
        if scene == self._scene:
            return
        self._scene = scene
        self._paint_scene_buttons()
        self._render_scene()

    # ---- 加载 ----

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._auto_timer.start()

    def hideEvent(self, event) -> None:
        self._auto_timer.stop()
        super().hideEvent(event)

    def _auto_refresh(self) -> None:
        """自动刷新：只在可见、未最小化且没有请求在飞时静默拉一次。"""
        if not self.isVisible():
            return
        if self.windowState() & QtCore.Qt.WindowState.WindowMinimized:
            return
        if self._pending or not self.refresh_button.isEnabled():
            return
        self._silent = True
        self.api.start()

    def load(self) -> None:
        self._silent = False
        self._data = {}
        self._errors = {}
        self._pending = set()
        self._required_failed = False
        self.status_label.show_info("正在读取今日数据…")
        self.retry_button.hide()
        self.refresh_button.setEnabled(False)
        self.banner.hide()
        self.api.start()

    def _on_ready(self) -> None:
        self._silent = False      # 连上了就不算「自动刷新失败」了
        self._pending = {"overview", "today", "settings", "briefing"}
        self.api.get("/api/overview", lambda data: self._ok("overview", data),
                     lambda message: self._fail("overview", message))
        self.api.get("/api/today", lambda data: self._ok("today", data),
                     lambda message: self._fail("today", message))
        self.api.get("/api/settings", lambda data: self._ok("settings", data),
                     lambda message: self._fail("settings", message))
        self.api.get("/api/briefing/today",
                     lambda data: self._ok("briefing", data),
                     lambda message: self._fail("briefing", message))

    def _on_failed(self, message: str) -> None:
        silent = self._silent
        self._silent = False
        if silent:
            self.status_label.show_info(f"自动刷新没连上（显示上次数据）：{message}")
            return
        self.status_label.show_err(message)
        self.retry_button.show()
        self.refresh_button.setEnabled(True)

    def _ok(self, key: str, data) -> None:
        self._data[key] = data if isinstance(data, dict) else {}
        self._pending.discard(key)
        if key == "overview":
            self.hero.update_overview(self._data[key])
            self._render_week()
            self._render_achievements()
            self._render_continue()
        if key == "today":
            self._render_continue()
            self._render_timeline()
            self._render_week()
        if key == "settings":
            self._render_onboarding()
            self._render_briefing()
        if key == "briefing":
            self._render_briefing()
        self._finish()

    def _fail(self, key: str, message: str) -> None:
        self._errors[key] = message
        self._pending.discard(key)
        if key in {"overview", "today"}:
            self._required_failed = True
            self.status_label.show_err(f"今日数据没读出来：{message}")
            self.retry_button.show()
            self.refresh_button.setEnabled(True)
            return
        self._finish()

    def _finish(self) -> None:
        if self._pending:
            if not self._required_failed:
                self.status_label.show_info("部分数据还在加载…")
            return
        self._silent = False
        self.refresh_button.setEnabled(True)
        if self._required_failed:
            return
        if self._errors:
            names = {"settings": "设置", "briefing": "今日简报"}
            missed = "、".join(names.get(key, key) for key in self._errors)
            self.status_label.show_info(f"已更新（{missed}没读到）")
            return
        now = QtCore.QTime.currentTime().toString("HH:mm")
        self.status_label.show_ok(f"已更新 · {now}")

    # ---- 渲染 ----

    def _render_briefing(self) -> None:
        settings = self._data.get("settings") or {}
        enabled = (settings.get("briefing") or {}).get("enabled", True) is not False
        self.briefing.set_data(self._data.get("briefing"), enabled)

    def _render_onboarding(self) -> None:
        settings = self._data.get("settings")
        if not settings:
            self.banner.hide()
            return
        ready = (settings.get("agent") or {}).get("ready")
        self.banner.setVisible(ready is False)

    def _configure(self) -> None:
        if self._open_settings is not None:
            self._open_settings()
        else:
            self._navigate("#/settings")

    # ---- 响应式 ----

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_bottom_layout()
