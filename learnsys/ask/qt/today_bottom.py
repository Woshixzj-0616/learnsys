"""今日页底栏（R5）：时间线 + 侧栏四面板 + 快捷入口 + 响应式堆叠。

数据拉取在 `today.py`，控件在 `today_panels.py`；本文件只负责组装与渲染。
"""
from __future__ import annotations

from urllib.parse import quote

from PySide6 import QtWidgets

from .today_panels import (AchievementRow, InfoPanel, ShortcutButton,
                           TimelineSection)
from .today_widgets import minutes_parts

BREAK = 880              # 行动卡/插件卡/底栏堆叠共用的宽度断点
SIDE_WIDTH = 320         # 右侧栏固定宽度（Web 是 292，Qt 给长标题多留一点）


class TodayBottomMixin:
    """宿主约定：提供 `_navigate(href)`、`status_label`、`_data`、`tokens`、
    `_bottom_stacked`；本类只组装与渲染，不拉数据。"""

    def _build_bottom(self, body: QtWidgets.QVBoxLayout) -> None:
        if not hasattr(self, "_bottom_stacked"):
            self._bottom_stacked = False
        self.bottom = QtWidgets.QWidget()
        self.bottom.setObjectName("TodayBottom")
        self.bottom_grid = QtWidgets.QGridLayout(self.bottom)
        self.bottom_grid.setContentsMargins(0, 0, 0, 0)
        self.bottom_grid.setHorizontalSpacing(24)
        self.bottom_grid.setVerticalSpacing(24)

        self.timeline = TimelineSection(self.tokens)
        self.timeline.opened.connect(self._open_timeline)
        self.bottom_grid.addWidget(self.timeline, 0, 0)

        self.side = QtWidgets.QWidget()
        self.side.setObjectName("TodaySide")
        self.side.setFixedWidth(SIDE_WIDTH)
        side_box = QtWidgets.QVBoxLayout(self.side)
        side_box.setContentsMargins(0, 0, 0, 0)
        side_box.setSpacing(12)

        self.week_panel = InfoPanel("本周")
        self.cet6_panel = InfoPanel("六级精听断点")
        self.cet6_panel.hide()
        self.cet6_panel.row_clicked.connect(self._navigate)
        self.focus_panel = InfoPanel("专注")
        self.ach_panel = InfoPanel("成就")
        side_box.addWidget(self.week_panel)
        side_box.addWidget(self.cet6_panel)
        side_box.addWidget(self.focus_panel)
        side_box.addWidget(self.ach_panel)
        side_box.addSpacing(4)

        self.ask_shortcut = ShortcutButton("问一个问题", "进入问一问")
        self.ask_shortcut.clicked.connect(lambda: self._navigate("#/ask"))
        self.netlab_shortcut = ShortcutButton("去训练场练一格", "子网 / 路由 / 抓包")
        self.netlab_shortcut.clicked.connect(lambda: self._navigate("#/netlab"))
        self.continue_shortcut = ShortcutButton("继续最近的会话", "接着上次")
        self.continue_shortcut.clicked.connect(self._continue_last)
        shortcut_box = QtWidgets.QVBoxLayout()
        shortcut_box.setContentsMargins(0, 0, 0, 0)
        shortcut_box.setSpacing(7)
        for button in (self.ask_shortcut, self.netlab_shortcut,
                       self.continue_shortcut):
            shortcut_box.addWidget(button)
        side_box.addLayout(shortcut_box)
        side_box.addStretch(1)
        self.bottom_grid.addWidget(self.side, 0, 1)
        self.bottom_grid.setColumnStretch(0, 1)
        body.addWidget(self.bottom)

    # ---- 渲染 ----

    def _render_timeline(self) -> None:
        asks = (self._data.get("today") or {}).get("asks") or []
        self.timeline.set_items(asks if isinstance(asks, list) else [])

    def _render_week(self) -> None:
        week = (self._data.get("overview") or {}).get("week") or {}
        minutes = minutes_parts(week.get("minutes") or 0)
        self.week_panel.set_rows([
            {"label": "活跃天数",
             "value": f"{int(week.get('active_days') or 0)} / 7"},
            {"label": "专注时长", "value": f"{minutes[0]} {minutes[1]}"},
            {"label": "问答", "value": f"{int(week.get('asks') or 0)} 条"},
        ])

    def _render_focus(self) -> None:
        focus = (self._data.get("today") or {}).get("focus") or {}
        minutes = minutes_parts(focus.get("minutes"))
        rows = [
            {"label": "专注时长", "value": f"{minutes[0]} {minutes[1]}"},
            {"label": "窗口切换",
             "value": f"{int(focus.get('switches') or 0)} 次"},
        ]
        apps = focus.get("apps") if isinstance(focus.get("apps"), list) else []
        for app in apps:
            try:
                name, value = app[0], app[1]
            except (TypeError, IndexError):
                continue
            rows.append({"label": str(name), "value": f"{float(value):.0f} 分钟"})
        self.focus_panel.set_rows(rows)
        if not apps:
            self.focus_panel.set_note(
                "今天还没有开始录制。托盘里点「开始完整录制」才有专注数据。")

    def _render_cet6(self) -> None:
        items = (self._data.get("today") or {}).get("cet6") or []
        if not items:
            self.cet6_panel.hide()
            return
        rows = []
        for item in items:
            title = " · ".join(part for part in (
                str(item.get("paper") or "六级"),
                str(item.get("section") or ""),
                str(item.get("item") or "")) if part)
            paper = str(item.get("paper_id") or item.get("paper") or "")
            rows.append({
                "label": title,
                "value": f"{int(item.get('count') or 0)} 个断点",
                "href": f"#/cet6?paper={quote(paper, safe='')}" if paper else "",
            })
        self.cet6_panel.set_rows(rows)
        self.cet6_panel.show()

    def _render_achievements(self) -> None:
        items = (self._data.get("overview") or {}).get("achievements") or []
        earned = [item for item in items if item.get("earned")]
        locked = [item for item in items if not item.get("earned")]
        self.ach_panel.set_hint(f"{len(earned)} / {len(items)}")
        self.ach_panel.set_widgets(
            [AchievementRow(item) for item in (earned + locked)[:8]])
        if not items:
            self.ach_panel.set_note("还没有可显示的成就。")

    def _render_continue(self) -> None:
        items = (self._data.get("conversations") or {}).get("items") or []
        self._continue_conv = ""
        for item in items:
            if int(item.get("messages") or 0) > 0:
                self._continue_conv = str(item.get("id") or "")
                break

    # ---- 跳转 ----

    def _open_timeline(self, conversation_id: str) -> None:
        if conversation_id:
            self._navigate(f"#/ask/{conversation_id}")
        else:
            self.status_label.show_info(
                "这条是快捷栏问的，暂时只能在横栏历史里看")

    def _continue_last(self) -> None:
        if self._continue_conv:
            self._navigate(f"#/ask/{self._continue_conv}")
            return
        self.status_label.show_info("还没有会话，先问一个问题吧")
        self._navigate("#/ask")

    # ---- 响应式 ----

    def _apply_bottom_layout(self) -> None:
        stacked = self.width() < BREAK
        if stacked == self._bottom_stacked:
            return
        self._bottom_stacked = stacked
        self.bottom_grid.removeWidget(self.timeline)
        self.bottom_grid.removeWidget(self.side)
        if stacked:
            self.side.setMinimumWidth(0)
            self.side.setMaximumWidth(16777215)
            self.bottom_grid.addWidget(self.timeline, 0, 0)
            self.bottom_grid.addWidget(self.side, 1, 0)
        else:
            self.side.setFixedWidth(SIDE_WIDTH)
            self.bottom_grid.addWidget(self.timeline, 0, 0)
            self.bottom_grid.addWidget(self.side, 0, 1)
        self.bottom_grid.setColumnStretch(0, 1)
        self.bottom_grid.setColumnStretch(1, 0)
