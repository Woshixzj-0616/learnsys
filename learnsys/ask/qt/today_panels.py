"""今日页补全面板：问答轨道、本周柱状图、成就折叠、纯文本摘要。

只负责长什么样与单块自渲染；数据拉取和跳转仍在 `today.py`。
颜色走 `style.color()`（令牌来自 `web/css/tokens.css`），不写第二份配色表。
"""
from __future__ import annotations

import re

from PySide6 import QtCore, QtGui, QtWidgets

from . import style
from . import tokens as token_source
from .today_widgets import ClickableCard, _click_through, _label

PERIODS = ("凌晨", "上午", "下午", "晚上")


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
    """本周七天柱状图：柱高=当天学习分钟，0 用一条细底线。"""

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
            achieved = bool(day.get("goal_achieved"))
            if minutes > 0:
                height = max(3.0, self.BAR_AREA * minutes / peak)
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(style.color(
                    values["--mark"] if achieved else values["--line-strong"]))
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
            is_today = str(day.get("date") or "") == QtCore.QDate.currentDate().toString("yyyy-MM-dd")
            painter.setPen(style.color(
                values["--mark"] if (achieved or is_today) else values["--text-faint"]))
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


class GroupHead(QtWidgets.QWidget):
    """时段分组头：晚上 —— 5 条。"""

    def __init__(self, label: str, count: int,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TimelineGroup")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 8, 0, 2)
        row.setSpacing(9)
        row.addWidget(_label(label, "TimelineGroupLabel"), 0)
        line = QtWidgets.QFrame()
        line.setObjectName("TimelineGroupLine")
        line.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        line.setFixedHeight(1)
        row.addWidget(line, 1)
        row.addWidget(_label(f"{count} 条", "TimelineGroupCount"), 0)


class TimelineRail(QtWidgets.QWidget):
    """问答轨道：一条竖线 + 一个圆点（图片用 mark，代码用 ok）。"""

    def __init__(self, tokens: dict | None = None, image: bool = False,
                 code: bool = False, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        values = token_source.merged(tokens)
        self._line = style.color(values["--line"])
        self._bg = style.color(values["--surface"])
        self._dot = style.color(
            values["--mark"] if image else values["--ok"] if code else values["--accent"])
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
    """一条今日问答：时间 + 轨道 + 问句 + 两行摘要。"""

    def __init__(self, ask: dict, tokens: dict | None = None,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TimelineItem")
        self.conversation_id = str(ask.get("conversation_id") or "")
        question = str(ask.get("question") or "").strip()
        answer = str(ask.get("answer") or "")
        image = ask.get("kind") == "image"
        code = not image and looks_code(question)
        self.setAccessibleName(_question_label(question)[:60] or "问答")

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 4, 8, 10)
        row.setSpacing(8)
        self.time = _label(time_of(ask.get("ts")), "TimelineTime")
        self.time.setFixedWidth(40)
        self.time.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.time, 0)
        row.addWidget(TimelineRail(tokens, image, code), 0)

        main = QtWidgets.QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(2)
        question_row = QtWidgets.QHBoxLayout()
        question_row.setSpacing(6)
        self.question = _label(_question_label(question), "TimelineQ")
        self.question.setWordWrap(True)
        question_row.addWidget(self.question, 1)
        self.tag = _label("图" if image else "代码", "TimelineTag")
        self.tag.setVisible(image or code)
        question_row.addWidget(self.tag, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        main.addLayout(question_row)

        self.answer = _label(plain(answer, 110), "TimelineA")
        self.answer.setWordWrap(True)
        self.answer.setMaximumHeight(34)
        main.addWidget(self.answer)
        row.addLayout(main, 1)
        _click_through(self)


def time_of(stamp) -> str:
    text = str(stamp or "")
    return text[11:16] if len(text) >= 16 else text


def looks_code(text: str) -> bool:
    value = str(text or "")
    return ("\n" in value
            or bool(re.search(r"```|#include|^\s*(def|class|function|import|from|package)\b",
                              value, re.MULTILINE)))


def _question_label(question: str) -> str:
    if not looks_code(question):
        return plain(question, 120)
    lines = len([line for line in question.split("\n") if line.strip()])
    lang = " C++" if re.search(r"#include|std::|cout|cin|class\s+\w+", question) else ""
    return f"粘贴了一段{lang} 代码（约 {lines} 行）" if lang else f"粘贴了一段代码（约 {lines} 行）"


def period_of(stamp) -> str:
    try:
        hour = int(str(stamp or "")[11:13])
    except (TypeError, ValueError):
        return "其他"
    if hour < 6:
        return PERIODS[0]
    if hour < 12:
        return PERIODS[1]
    if hour < 18:
        return PERIODS[2]
    return PERIODS[3]


class TimelineSection(QtWidgets.QWidget):
    """问答区块：按上午 / 下午 / 晚上分组的轨道；空时给一句引导。"""

    opened = QtCore.Signal(str)

    def __init__(self, tokens: dict | None = None,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TimelineCard")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.tokens = tokens
        self.items: list[TimelineItem] = []
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(18, 16, 20, 14)
        box.setSpacing(8)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        heading = _label("今天的问答", "SectionTitle")
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

    def set_items(self, asks: list[dict], ask_count: int = 0) -> None:
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.items = []
        shown = [ask for ask in (asks or []) if isinstance(ask, dict)][:6]
        total = max(int(ask_count or 0), len(asks or []))
        if not shown:
            self.count.setText("今天还没有问答")
            self.empty.show()
            return
        self.empty.hide()
        self.count.setText(f"{total} 条记录 · 最近 {len(shown)} 条"
                           if total > len(shown) else f"{total} 条记录")

        groups: list[tuple[str, list[dict]]] = []
        for ask in shown:
            label = period_of(ask.get("ts"))
            if not groups or groups[-1][0] != label:
                groups.append((label, []))
            groups[-1][1].append(ask)

        for label, group in groups:
            self.list_box.addWidget(GroupHead(label, len(group)))
            for ask in group:
                entry = TimelineItem(ask, self.tokens)
                entry.clicked.connect(
                    lambda conv=entry.conversation_id: self.opened.emit(conv))
                self.items.append(entry)
                self.list_box.addWidget(entry)


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
