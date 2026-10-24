"""今日页（Qt 试点，R4）。

数据全部来自现有 `/api/*`；本页只负责展示与跳转。
颜色/字号/圆角沿用 `style.py`（令牌来自 `web/css/tokens.css`）。
"""
from __future__ import annotations

import datetime

from PySide6 import QtCore, QtWidgets

from learnsys import product

from . import style
from . import tokens as token_source
from .today_bottom import BREAK, TodayBottomMixin
from .today_widgets import (ActionCard, HeroCard, OnboardingBanner, PluginCard,
                            StatStrip, chars_parts, minutes_parts)
from .widgets import StatusLabel

TODAY_SIZE = (1040, 700)
TODAY_MIN = (760, 560)
CONTENT_MAX = 1040
# BREAK 由 today_bottom 统一提供：行动卡/插件卡/底栏堆叠共用一个断点。


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
        self._action_cols = 0
        self._plugin_cols = 0
        self._bottom_stacked = False
        self._continue_conv = ""
        self.action_cards: list[ActionCard] = []
        self.plugin_cards: list[PluginCard] = []

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
        self.refresh_button = QtWidgets.QPushButton("刷新")
        self.refresh_button.clicked.connect(self.load)
        self.open_button = QtWidgets.QPushButton("打开工作台")
        self.open_button.setObjectName("Primary")
        self.open_button.clicked.connect(lambda: self._navigate("#/today"))
        head.addWidget(self.refresh_button)
        head.addWidget(self.open_button)
        column.addLayout(head)

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

        self.hero = HeroCard()
        body.addWidget(self.hero)

        # 顺序照 Web 今日页：Hero → 插件舞台 → 统计条 → 行动卡
        self.plugin_section, self.plugin_grid = self._grid_section(
            "插件舞台", "点卡片进入 · 插件中心可开关")
        self.plugin_empty = QtWidgets.QLabel("插件清单没读到；点「刷新」再试。")
        self.plugin_empty.setObjectName("Empty")
        self.plugin_empty.setWordWrap(True)
        self.plugin_empty.hide()
        self.plugin_section.layout().addWidget(self.plugin_empty)
        body.addWidget(self.plugin_section)

        self.stats = StatStrip()
        body.addWidget(self.stats)

        self.action_section, self.action_grid = self._grid_section("今天最值得做的三件事")
        body.addWidget(self.action_section)

        self._build_bottom(body)

        body.addStretch(1)
        scroll.setWidget(content)
        column.addWidget(scroll, 1)

    def _grid_section(self, title: str, hint: str = ""):
        holder = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        head = QtWidgets.QHBoxLayout()
        heading = QtWidgets.QLabel(title)
        heading.setObjectName("SectionTitle")
        head.addWidget(heading)
        head.addStretch(1)
        if hint:
            hint_label = QtWidgets.QLabel(hint)
            hint_label.setObjectName("Hint")
            head.addWidget(hint_label)
        box.addLayout(head)
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        box.addLayout(grid)
        return holder, grid

    # ---- 加载 ----

    def load(self) -> None:
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
        self._pending = {"overview", "today", "modules", "settings", "review",
                         "conversations"}
        self.api.get("/api/overview", lambda data: self._ok("overview", data),
                     lambda message: self._fail("overview", message))
        self.api.get("/api/today", lambda data: self._ok("today", data),
                     lambda message: self._fail("today", message))
        self.api.get("/api/modules", lambda data: self._ok("modules", data),
                     lambda message: self._fail("modules", message))
        self.api.get("/api/settings", lambda data: self._ok("settings", data),
                     lambda message: self._fail("settings", message))
        self.api.get("/api/review/stats", lambda data: self._ok("review", data),
                     lambda message: self._fail("review", message))
        self.api.get("/api/conversations?limit=8",
                     lambda data: self._ok("conversations", data),
                     lambda message: self._fail("conversations", message))

    def _on_failed(self, message: str) -> None:
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
        if key == "today":
            self._render_stats()
            self._render_actions(self._data[key].get("actions") or [])
            self._render_timeline()
            self._render_focus()
            self._render_cet6()
        if key in {"overview", "today", "modules", "settings"}:
            self._render_plugins()
        if key == "settings":
            self._render_onboarding()
        if key == "conversations":
            self._render_continue()
        if key == "review":
            self._render_stats()
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
        self.refresh_button.setEnabled(True)
        if self._required_failed:
            return
        if self._errors:
            names = {"modules": "插件清单", "settings": "设置",
                     "review": "复习统计", "conversations": "最近会话"}
            missed = "、".join(names.get(key, key) for key in self._errors)
            self.status_label.show_info(f"已更新（{missed}没读到）")
            return
        now = QtCore.QTime.currentTime().toString("HH:mm")
        self.status_label.show_ok(f"已更新 · {now}")

    # ---- 渲染 ----

    def _render_stats(self) -> None:
        today = self._data.get("today") or {}
        review = self._data.get("review") or {}
        focus = minutes_parts((today.get("focus") or {}).get("minutes"))
        chars = chars_parts((today.get("transcripts") or {}).get("chars"))
        asks = today.get("asks") or []
        image_asks = sum(1 for ask in asks if ask.get("kind") == "image")
        reviewed = review.get("reviewed_today")
        next_due = review.get("next_due")
        if reviewed:
            review_note = f"今天已复习 {reviewed} 条"
        elif next_due:
            review_note = f"下张 {next_due} 到期"
        else:
            review_note = "今天没有到期的"
        self.stats.update_stats([
            {"label": "专注", "value": focus[0], "unit": focus[1],
             "note": f"切换 {(today.get('focus') or {}).get('switches') or 0} 次"},
            {"label": "问答", "value": str(today.get("ask_count") or 0), "unit": "条",
             "note": f"最近 10 条里 {image_asks} 条带图" if image_asks else "今天的提问"},
            {"label": "课堂转写",
             "value": str((today.get("transcripts") or {}).get("count") or 0),
             "unit": "段", "note": f"{chars[0]} {chars[1]}"},
            {"label": "今日计划", "value": str(today.get("due_reviews") or 0),
             "unit": "条到期", "note": review_note},
        ])

    def _render_actions(self, actions: list) -> None:
        self._clear_grid(self.action_grid)
        self.action_cards = []
        if not actions:
            self.action_section.hide()
            return
        self.action_section.show()
        for index, item in enumerate(actions[:3]):
            card = ActionCard(item or {})
            card.set_number(index + 1)
            card.clicked.connect(lambda c=card: self._navigate(c.href))
            self.action_cards.append(card)
        self._action_cols = 0
        self._apply_columns()

    def _render_plugins(self) -> None:
        modules = (self._data.get("modules") or {}).get("modules")
        modules = modules if isinstance(modules, list) else []
        prefs = (self._data.get("settings") or {}).get("modules") or {}
        today = (self._data.get("overview") or {}).get("today") or {}
        counts = {
            "ask": f"{int(today.get('asks') or 0)} 问",
            "netlab": f"{int(today.get('netlab') or 0)} 个训练",
            "cet6": f"{int(today.get('cet6') or 0)} 个断点",
            "review": f"{int(today.get('review') or 0)} 次复盘",
            "quiz": f"{int(today.get('quiz') or 0)} 场测验",
        }
        selected = [
            module for module in modules
            if module.get("home") and module.get("status") == "ready"
            and prefs.get(module.get("id"), True) is not False
        ]
        selected.sort(key=lambda item: (int(item.get("order") or 999),
                                        str(item.get("id") or "")))

        self._clear_grid(self.plugin_grid)
        self.plugin_cards = []
        if not selected:
            self.plugin_empty.setText(
                "插件都被关掉了 —— 到设置里打开。" if modules
                else "插件清单没读到；点「刷新」再试。")
            self.plugin_empty.show()
            return
        self.plugin_empty.hide()
        for module in selected:
            card = PluginCard(module, counts.get(str(module.get("id") or ""), "打开"))
            card.clicked.connect(lambda c=card: self._navigate(c.href))
            self.plugin_cards.append(card)
        self._plugin_cols = 0
        self._apply_columns()

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
        self._apply_columns()

    def _apply_columns(self) -> None:
        if not hasattr(self, "bottom_grid"):
            return
        action_cols = 3 if self.width() >= BREAK else 1
        plugin_cols = 3 if self.width() >= BREAK else 2
        if self.action_cards and action_cols != self._action_cols:
            self._action_cols = action_cols
            self._place(self.action_grid, self.action_cards, action_cols)
        if self.plugin_cards and plugin_cols != self._plugin_cols:
            self._plugin_cols = plugin_cols
            self._place(self.plugin_grid, self.plugin_cards, plugin_cols)
        self._apply_bottom_layout()

    @staticmethod
    def _place(grid: QtWidgets.QGridLayout, cards: list, cols: int) -> None:
        for card in cards:
            grid.removeWidget(card)
        for index, card in enumerate(cards):
            grid.addWidget(card, index // cols, index % cols)
        for column in range(3):
            grid.setColumnStretch(column, 1 if column < cols else 0)
        for row in range((len(cards) + cols - 1) // cols):
            grid.setRowStretch(row, 1)

    @staticmethod
    def _clear_grid(grid: QtWidgets.QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
