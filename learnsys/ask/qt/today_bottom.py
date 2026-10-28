"""今日页底栏（R5）：时间线 + 侧栏四面板 + 快捷入口 + 响应式堆叠。

数据拉取在 `today.py`，控件在 `today_panels.py`；本文件只负责组装与渲染。
"""
from __future__ import annotations

from urllib.parse import quote

from PySide6 import QtWidgets

from .today_panels import (AchievementRow, InfoPanel, ShortcutButton,
                           TimelineSection, WeekBars)
from .today_widgets import minutes_parts

BREAK = 880              # 行动卡/插件卡/底栏堆叠共用的宽度断点
SIDE_WIDTH = 320         # 右侧栏固定宽度（Web 是 292，Qt 给长标题多留一点）

# 快捷入口按场景切换：与 Web 今日页的 only-study / only-work 区块同口径。
# 第三项 href 为空 = 不是跳页面，而是「接着上次」的会话恢复。
STUDY_SHORTCUTS = (
    ("问一个问题", "进入问一问", "#/ask"),
    ("去训练场练一格", "子网 / 路由 / 抓包", "#/netlab"),
    ("继续最近的会话", "接着上次", ""),
)
WORK_SHORTCUTS = (
    ("打开 Agent 中枢", "派活 / 只读执行", "#/agents"),
    ("看今天的运行记录", "模型、耗时与成本", "#/agentruns"),
    ("打开资料库", "导入的资料与笔记", "#/materials"),
)


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
        self.cet6_panel = InfoPanel("六级训练断点")
        self.cet6_panel.hide()
        self.cet6_panel.row_clicked.connect(self._navigate)
        self.focus_panel = InfoPanel("专注")
        self.ach_panel = InfoPanel("成就")
        side_box.addWidget(self.week_panel)
        side_box.addWidget(self.cet6_panel)
        side_box.addWidget(self.focus_panel)
        side_box.addWidget(self.ach_panel)
        side_box.addSpacing(4)

        self.shortcut_box = QtWidgets.QVBoxLayout()
        self.shortcut_box.setContentsMargins(0, 0, 0, 0)
        self.shortcut_box.setSpacing(7)
        side_box.addLayout(self.shortcut_box)
        self._render_shortcuts()
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
        active = int(week.get("active_days") or 0)
        bars = WeekBars(self.tokens)
        bars.set_days(week.get("daily") or [])
        note = QtWidgets.QLabel(
            f"共 {minutes[0]} {minutes[1]} · 活跃 {active} / 7 天")
        note.setObjectName("PanelNote")
        self.week_panel.set_hint("分钟 / 天")
        self.week_panel.set_widgets([bars, note])

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
                "今天还没有开始录像。托盘里点「开始录像」才有专注数据。")

    def _render_cet6(self) -> None:
        # 工作场景不显示六级断点；切回学习时再按数据恢复。
        if getattr(self, "_scene", "study") == "work":
            self.cet6_panel.hide()
            return
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

    def _render_shortcuts(self) -> None:
        """按当前场景重建快捷入口；学习 ↔ 工作切换时整组换掉。"""
        while self.shortcut_box.count():
            item = self.shortcut_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        work = getattr(self, "_scene", "study") == "work"
        buttons = []
        for text, hint, href in (WORK_SHORTCUTS if work else STUDY_SHORTCUTS):
            button = ShortcutButton(text, hint)
            if href:
                button.clicked.connect(
                    lambda _checked=False, target=href: self._navigate(target))
            else:
                button.clicked.connect(self._continue_last)
            self.shortcut_box.addWidget(button)
            buttons.append(button)
        # 保留具名引用：测试和外部代码不用按位置找按钮。
        if work:
            self.work_shortcuts = buttons
        elif len(buttons) == 3:
            (self.ask_shortcut, self.netlab_shortcut,
             self.continue_shortcut) = buttons

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
