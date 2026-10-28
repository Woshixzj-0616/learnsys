"""今日页底栏：接着上次 + 问答轨道，右侧本周 + 成就。

数据拉取在 `today.py`，控件在 `today_widgets.py` / `today_panels.py`；
本文件只负责组装与渲染。
"""
from __future__ import annotations

from PySide6 import QtWidgets

from .today_achievements import CollapsibleAchievements
from .today_panels import InfoPanel, TimelineSection, WeekBars
from .today_widgets import (ContinueCard, FactsStrip, WorkEntryCard,
                            minutes_parts)

BREAK = 880              # 左右两栏堆叠的宽度断点
SIDE_WIDTH = 320         # 右侧栏固定宽度


class TodayBottomMixin:
    """宿主约定：提供 `_navigate(href)`、`status_label`、`_data`、`tokens`、
    `_scene`、`_bottom_stacked`；本类只组装与渲染，不拉数据。"""

    def _build_bottom(self, body: QtWidgets.QVBoxLayout) -> None:
        if not hasattr(self, "_bottom_stacked"):
            self._bottom_stacked = False
        self.bottom = QtWidgets.QWidget()
        self.bottom.setObjectName("TodayBottom")
        self.bottom_grid = QtWidgets.QGridLayout(self.bottom)
        self.bottom_grid.setContentsMargins(0, 0, 0, 0)
        self.bottom_grid.setHorizontalSpacing(24)
        self.bottom_grid.setVerticalSpacing(24)

        self.left = QtWidgets.QWidget()
        self.left.setObjectName("TodayLeft")
        left_box = QtWidgets.QVBoxLayout(self.left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.setSpacing(12)

        self.continue_card = ContinueCard(self._navigate)
        self.work_card = WorkEntryCard(self._navigate)
        left_box.addWidget(self.continue_card)
        left_box.addWidget(self.work_card)

        self.timeline = TimelineSection(self.tokens)
        self.timeline.opened.connect(self._open_timeline)
        left_box.addWidget(self.timeline)

        self.side = QtWidgets.QWidget()
        self.side.setObjectName("TodaySide")
        self.side.setFixedWidth(SIDE_WIDTH)
        side_box = QtWidgets.QVBoxLayout(self.side)
        side_box.setContentsMargins(0, 0, 0, 0)
        side_box.setSpacing(12)

        self.week_panel = InfoPanel("本周投入")
        self.ach_card = CollapsibleAchievements()
        side_box.addWidget(self.week_panel)
        side_box.addWidget(self.ach_card)
        side_box.addStretch(1)

        self.bottom_grid.addWidget(self.left, 0, 0)
        self.bottom_grid.addWidget(self.side, 0, 1)
        self.bottom_grid.setColumnStretch(0, 1)
        body.addWidget(self.bottom)

    # ---- 渲染 ----

    def _render_continue(self) -> None:
        today = self._data.get("today") or {}
        overview_today = (self._data.get("overview") or {}).get("today") or {}
        self.continue_card.set_data(
            today.get("cet6") or [],
            overview_today.get("goal_tasks") or [],
            today.get("actions") or [])

    def _render_week(self) -> None:
        week = (self._data.get("overview") or {}).get("week") or {}
        minutes = minutes_parts(week.get("study_minutes") or week.get("minutes") or 0)
        achieved = int(week.get("achieved_days") or 0)
        goal_days = int(week.get("goal_days") or 5)
        active = int(week.get("active_days") or 0)
        bars = WeekBars(self.tokens)
        bars.set_days(week.get("daily") or [])
        note = QtWidgets.QLabel(
            f"共 {minutes[0]} {minutes[1]} · 活跃 {active} / 7 天")
        note.setObjectName("PanelNote")
        facts = FactsStrip()
        facts.set_facts(self._facts())
        self.week_panel.set_hint(f"达标 {achieved} / {goal_days} 天")
        self.week_panel.set_widgets([bars, note, facts])

    def _facts(self) -> list[dict]:
        today = self._data.get("today") or {}
        overview_today = (self._data.get("overview") or {}).get("today") or {}
        activity = today.get("activity") or {}
        cet6 = today.get("cet6") if isinstance(today.get("cet6"), list) else []
        cet6_total = sum(int(item.get("count") or 0) for item in cet6
                         if isinstance(item, dict))
        return [
            {"value": int(today.get("ask_count") or overview_today.get("asks") or 0),
             "label": "问答"},
            {"value": cet6_total, "label": "听力断点"},
            {"value": int(overview_today.get("netlab") or 0)
                      + int(activity.get("trains") or 0), "label": "训练"},
            {"value": round(float(today.get("study_measured") or 0)),
             "unit": "分钟", "label": "实测专注"},
        ]

    def _render_timeline(self) -> None:
        today = self._data.get("today") or {}
        asks = today.get("asks") or []
        self.timeline.set_items(asks if isinstance(asks, list) else [],
                                int(today.get("ask_count") or 0))

    def _render_achievements(self) -> None:
        items = (self._data.get("overview") or {}).get("achievements") or []
        self.ach_card.set_items(items if isinstance(items, list) else [])

    def _render_scene(self) -> None:
        work = getattr(self, "_scene", "study") == "work"
        self.continue_card.setVisible(not work)
        self.work_card.setVisible(work)

    # ---- 跳转 ----

    def _open_timeline(self, conversation_id: str) -> None:
        if conversation_id:
            self._navigate(f"#/ask/{conversation_id}")
        else:
            self.status_label.show_info(
                "这条是快捷栏问的，暂时只能在横栏历史里看")

    # ---- 响应式 ----

    def _apply_bottom_layout(self) -> None:
        stacked = self.width() < BREAK
        if stacked == self._bottom_stacked:
            return
        self._bottom_stacked = stacked
        self.bottom_grid.removeWidget(self.left)
        self.bottom_grid.removeWidget(self.side)
        if stacked:
            self.side.setMinimumWidth(0)
            self.side.setMaximumWidth(16777215)
            self.bottom_grid.addWidget(self.left, 0, 0)
            self.bottom_grid.addWidget(self.side, 1, 0)
        else:
            self.side.setFixedWidth(SIDE_WIDTH)
            self.bottom_grid.addWidget(self.left, 0, 0)
            self.bottom_grid.addWidget(self.side, 0, 1)
        self.bottom_grid.setColumnStretch(0, 1)
        self.bottom_grid.setColumnStretch(1, 0)
