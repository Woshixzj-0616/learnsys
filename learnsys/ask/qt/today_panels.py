"""今日页补全面板（R5）：时间线、侧栏面板、成就行、快捷入口。

只负责长什么样与单块自渲染；数据拉取和跳转仍在 `today.py`。
颜色走 `style.color()`（令牌来自 `web/css/tokens.css`），不写第二份配色表。
"""
from __future__ import annotations

import re

from PySide6 import QtCore, QtGui, QtWidgets

from . import style
from . import tokens as token_source
from .today_widgets import ClickableCard, _click_through


def _label(text: str = "", name: str = "") -> QtWidgets.QLabel:
    node = QtWidgets.QLabel(text)
    if name:
        node.setObjectName(name)
    return node


def _separator() -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setObjectName("PanelSep")
    line.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
    line.setFixedHeight(1)
    return line


class InfoPanel(QtWidgets.QWidget):
    """侧栏一块面板：头（标题 + 右侧计数）+ 若干行。"""

    row_clicked = QtCore.Signal(str)

    def __init__(self, title: str, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("InfoPanel")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.rows: list[PanelRow] = []

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QtWidgets.QWidget()
        head.setObjectName("PanelHead")
        head.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        head_row = QtWidgets.QHBoxLayout(head)
        head_row.setContentsMargins(14, 11, 14, 9)
        head_row.setSpacing(8)
        self.heading = _label(title, "PanelTitle")
        self.hint = _label("", "PanelHint")
        self.hint.hide()
        head_row.addWidget(self.heading)
        head_row.addStretch(1)
        head_row.addWidget(self.hint)
        outer.addWidget(head)

        body = QtWidgets.QWidget()
        body.setObjectName("PanelBody")
        self.body = QtWidgets.QVBoxLayout(body)
        self.body.setContentsMargins(14, 8, 14, 10)
        self.body.setSpacing(0)
        outer.addWidget(body)

    def set_hint(self, text: str) -> None:
        self.hint.setText(str(text or ""))
        self.hint.setVisible(bool(text))

    def clear(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.rows = []

    def set_rows(self, rows: list[dict]) -> None:
        self.clear()
        for index, row in enumerate(rows):
            if index:
                self.body.addWidget(_separator())
            item = PanelRow(
                str(row.get("label") or ""), str(row.get("value") or ""),
                href=str(row.get("href") or ""),
                tooltip=str(row.get("tooltip") or ""))
            if item.href:
                item.clicked.connect(lambda href=item.href: self.row_clicked.emit(href))
            self.rows.append(item)
            self.body.addWidget(item)

    def set_widgets(self, widgets: list[QtWidgets.QWidget],
                    separated: bool = False) -> None:
        self.clear()
        for index, widget in enumerate(widgets):
            if index and separated:
                self.body.addWidget(_separator())
            self.body.addWidget(widget)

    def set_note(self, text: str) -> None:
        note = _label(str(text or ""), "PanelNote")
        note.setWordWrap(True)
        self.body.addWidget(note)


class WeekBars(QtWidgets.QWidget):
    """本周七天柱状图：柱高=当天专注分钟，0 用一条细底线。"""

    BAR_AREA = 52
    TOP = 16

    def __init__(self, tokens: dict | None = None,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("WeekBars")
        self.setFixedHeight(self.TOP + self.BAR_AREA + 20)
        self._tokens = token_source.merged(
            tokens if tokens is not None else token_source.read_web_tokens())
        self.days: list[dict] = []

    def set_days(self, days) -> None:
        self.days = [day for day in (days or []) if isinstance(day, dict)][-7:]
        self.update()

    def paintEvent(self, _event) -> None:
        values = self._tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        if not self.days:
            painter.end()
            return

        slot = self.width() / len(self.days)
        bar_w = min(12.0, slot * 0.42)
        base = float(self.TOP + self.BAR_AREA)
        peak = max([float(day.get("study_minutes") or day.get("minutes") or 0)
                    for day in self.days] + [1.0])

        font = QtGui.QFont(self.font())
        font.setPixelSize(10)
        painter.setFont(font)
        num_font = QtGui.QFont(font)
        num_font.setPixelSize(10)

        for index, day in enumerate(self.days):
            center = slot * (index + 0.5)
            minutes = float(day.get("study_minutes") or day.get("minutes") or 0)
            if minutes > 0:
                height = max(3.0, self.BAR_AREA * minutes / peak)
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(style.color(
                    values["--mark"] if day.get("goal_achieved") else values["--accent"]))
                painter.drawRoundedRect(
                    QtCore.QRectF(center - bar_w / 2, base - height, bar_w, height),
                    3.0, 3.0)
                painter.setFont(num_font)
                painter.setPen(style.color(values["--text-dim"]))
                painter.drawText(
                    QtCore.QRectF(center - 20, base - height - 16, 40, 14),
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    f"{minutes:g}")
            else:
                pen = QtGui.QPen(style.color(values["--line-strong"]), 2)
                pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(QtCore.QPointF(center - bar_w / 2, base),
                                 QtCore.QPointF(center + bar_w / 2, base))

            painter.setFont(font)
            painter.setPen(style.color(values["--text-faint"]))
            painter.drawText(
                QtCore.QRectF(center - 20, base + 4, 40, 16),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                weekday_label(day.get("date")))
        painter.end()


def weekday_label(date_text) -> str:
    try:
        day = QtCore.QDate.fromString(str(date_text or ""), "yyyy-MM-dd")
        if day.isValid():
            return "一二三四五六日"[day.dayOfWeek() - 1]
    except (TypeError, ValueError):
        pass
    return ""


class PanelRow(ClickableCard):
    """一行「左标签 / 右数值」；有 href 时整行可点。"""

    def __init__(self, label: str, value: str, href: str = "",
                 tooltip: str = "", parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PanelRow")
        self.href = href
        self.setProperty("clickable", bool(href))
        if not href:
            self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        if tooltip:
            self.setToolTip(tooltip)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 7, 0, 7)
        row.setSpacing(12)
        self.label = _label(label, "PanelRowLabel")
        self.label.setWordWrap(True)
        self.value = _label(value, "PanelRowValue")
        self.value.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                | QtCore.Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.label, 1)
        row.addWidget(self.value, 0)
        _click_through(self)


class AchievementRow(QtWidgets.QWidget):
    """成就行：✓/· + 名称 + 进度；已得用 `--mark-soft` 底。"""

    def __init__(self, item: dict, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AchRow")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.earned = bool(item.get("earned"))
        self.setProperty("earned", self.earned)
        self.setToolTip(str(item.get("desc") or ""))
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        self.dot = _label("✓" if self.earned else "·", "AchDot")
        self.name = _label(str(item.get("name") or ""), "AchName")
        self.progress = _label(
            f"{int(item.get('value') or 0)}/{int(item.get('target') or 0)}",
            "AchProgress")
        row.addWidget(self.dot, 0)
        row.addWidget(self.name, 1)
        row.addWidget(self.progress, 0)


class TimelineRail(QtWidgets.QWidget):
    """时间线左侧轨道：一条竖线 + 一个圆点（图片问句用强调色）。"""

    def __init__(self, tokens: dict | None = None, image: bool = False,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        values = token_source.merged(tokens)
        self._line = style.color(values["--line"])
        self._bg = style.color(values["--bg"])
        self._dot = style.color(values["--accent"] if image else values["--mark"])
        self.setFixedWidth(16)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QtGui.QPen(self._line, 1))
        painter.drawLine(QtCore.QPointF(7.5, 0), QtCore.QPointF(7.5, self.height()))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._bg)
        painter.drawEllipse(QtCore.QPointF(8, 10), 6, 6)
        painter.setBrush(self._dot)
        painter.drawEllipse(QtCore.QPointF(8, 10), 3.5, 3.5)
        painter.end()


class TimelineItem(ClickableCard):
    """一条今日问答：时间 + 问题（可带「图」）+ 纯文本摘要。"""

    def __init__(self, ask: dict, tokens: dict | None = None,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TimelineItem")
        self.conversation_id = str(ask.get("conversation_id") or "")
        question = " ".join(str(ask.get("question") or "").split())
        answer = str(ask.get("answer") or "")
        self.setAccessibleName(question[:60] or "问答")
        if len(question) > 120:
            question = question[:120] + "…"

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 3, 8, 14)
        row.setSpacing(6)
        row.addWidget(TimelineRail(tokens, ask.get("kind") == "image"), 0)

        main = QtWidgets.QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(2)
        self.time = _label(time_of(ask.get("ts")), "TimelineTime")
        main.addWidget(self.time)

        question_row = QtWidgets.QHBoxLayout()
        question_row.setSpacing(6)
        self.question = _label(question, "TimelineQ")
        self.question.setWordWrap(True)
        question_row.addWidget(self.question, 1)
        self.tag = _label("图", "TimelineTag")
        self.tag.setVisible(ask.get("kind") == "image")
        question_row.addWidget(self.tag, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        main.addLayout(question_row)

        self.answer = _label(plain(answer), "TimelineA")
        self.answer.setWordWrap(True)
        main.addWidget(self.answer)
        row.addLayout(main, 1)
        _click_through(self)


def time_of(stamp) -> str:
    text = str(stamp or "")
    return text[11:16] if len(text) >= 16 else text


class TimelineSection(QtWidgets.QWidget):
    """时间线区块：标题 + 计数 + 条目；空时给一句引导。"""

    opened = QtCore.Signal(str)

    def __init__(self, tokens: dict | None = None,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.tokens = tokens
        self.items: list[TimelineItem] = []
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        heading = _label("时间线", "SectionTitle")
        self.count = _label("", "Hint")
        head.addWidget(heading)
        head.addStretch(1)
        head.addWidget(self.count)
        box.addLayout(head)

        self.list_box = QtWidgets.QVBoxLayout()
        self.list_box.setContentsMargins(0, 0, 0, 0)
        self.list_box.setSpacing(0)
        box.addLayout(self.list_box)

        self.empty = _label(
            "今天还没有问答\n从问一问开始，每个问题都会自动记进这条时间线。",
            "EmptyState")
        self.empty.setWordWrap(True)
        self.empty.hide()
        box.addWidget(self.empty)
        box.addStretch(1)

    def set_items(self, asks: list[dict]) -> None:
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.items = []
        if not asks:
            self.count.setText("")
            self.empty.show()
            return
        self.empty.hide()
        self.count.setText(f"最近 {len(asks)} 条")
        for ask in asks:
            entry = TimelineItem(ask or {}, self.tokens)
            entry.clicked.connect(
                lambda conv=entry.conversation_id: self.opened.emit(conv))
            self.items.append(entry)
            self.list_box.addWidget(entry)


class ShortcutButton(ClickableCard):
    """侧栏底部快捷入口：左文案 + 右提示。"""

    def __init__(self, text: str, hint: str = "",
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Shortcut")
        self.setAccessibleName(text)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(10, 10, 12, 10)
        row.setSpacing(10)
        self.text = _label(text, "ShortcutText")
        self.hint = _label(hint, "ShortcutHint")
        row.addWidget(self.text, 1)
        row.addWidget(self.hint, 0)
        _click_through(self)


# ---- 纯文本摘要：与 `web/js/markdown.js::plain` 同口径 ----

_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MARKS = re.compile(r"[*_~>#-]+")
_SPACES = re.compile(r"\s+")


def plain(text, limit: int = 180) -> str:
    raw = _CODE_BLOCK.sub("［代码］", str(text or ""))
    raw = _INLINE_CODE.sub(r"\1", raw)
    raw = _IMAGE.sub("", raw)
    raw = _LINK.sub(r"\1", raw)
    raw = _HEADING.sub("", raw)
    raw = _MARKS.sub("", raw)
    raw = _SPACES.sub(" ", raw).strip()
    return raw[:limit] + "…" if len(raw) > limit else raw
