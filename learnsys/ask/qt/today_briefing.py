"""今日简报横条：1 条主稿 + 3 条次条。

只负责长什么样；数据、跳转在 `today.py`。样式走 QSS。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .today_widgets import ClickableCard, _click_through, _label, _short


class BriefLead(ClickableCard):
    """简报主稿：分类 + 标题 + 两行摘要 + 来源。"""

    def __init__(self, item: dict, navigate, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("BriefLead")
        self.href = "#/briefing"
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 22, 0)
        box.setSpacing(6)
        tag = _label(str(item.get("category_label") or ""), "BriefTagMark")
        box.addWidget(tag, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        self.title = _label(
            _short(item.get("title_zh") or item.get("title"), 52), "BriefLeadTitle")
        self.title.setWordWrap(True)
        box.addWidget(self.title)
        summary = _label(_short(item.get("summary"), 84), "BriefLeadSummary")
        summary.setWordWrap(True)
        box.addWidget(summary)
        source = _label(_source(item), "BriefSource")
        box.addWidget(source)
        box.addStretch(1)
        self.clicked.connect(lambda: navigate(self.href))
        _click_through(self)


class BriefRow(ClickableCard):
    """简报次条：分类 + 标题 + 来源。"""

    def __init__(self, item: dict, navigate, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("BriefRow")
        self.href = "#/briefing"
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 7, 0, 7)
        row.setSpacing(9)
        tag = _label(str(item.get("category_label") or ""), "BriefTag")
        tag.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        tag.setFixedHeight(20)
        tag.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                          QtWidgets.QSizePolicy.Policy.Fixed)
        row.addWidget(tag, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(2)
        self.title = _label(
            _short(item.get("title_zh") or item.get("title"), 52), "BriefRowTitle")
        self.title.setWordWrap(True)
        box.addWidget(self.title)
        box.addWidget(_label(_source(item), "BriefSource"))
        row.addLayout(box, 1)
        self.clicked.connect(lambda: navigate(self.href))
        _click_through(self)


def _source(item: dict) -> str:
    stamp = str(item.get("published_at") or "")
    time = stamp[11:16] if len(stamp) >= 16 else ""
    return " · ".join(part for part in (str(item.get("source") or ""), time) if part)


class BriefingBand(QtWidgets.QWidget):
    """今日简报：Hero 下面的整幅横条（1 条主稿 + 3 条次条）。"""

    def __init__(self, navigate, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("BriefingBand")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._navigate = navigate or (lambda _href: None)
        self.items: list[dict] = []
        self.rows: list[BriefRow] = []
        self.lead: BriefLead | None = None

        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(22, 16, 22, 14)
        box.setSpacing(12)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(12)
        heading = QtWidgets.QVBoxLayout()
        heading.setSpacing(3)
        self.eyebrow = _label("每日简报", "BriefEyebrow")
        self.title = _label("今天的简报", "BriefTitle")
        heading.addWidget(self.eyebrow)
        heading.addWidget(self.title)
        head.addLayout(heading, 1)
        self.meta = _label("", "BriefMeta")
        head.addWidget(self.meta, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.open_button = QtWidgets.QPushButton("打开简报 →")
        self.open_button.setObjectName("Ghost")
        self.open_button.clicked.connect(lambda: self._navigate("#/briefing"))
        head.addWidget(self.open_button, 0)
        box.addLayout(head)

        self.body = QtWidgets.QHBoxLayout()
        self.body.setSpacing(20)
        box.addLayout(self.body)

        self.empty = _label("", "EmptyState")
        self.empty.setWordWrap(True)
        self.empty.hide()
        box.addWidget(self.empty)
        self.hide()

    def set_data(self, data, enabled: bool = True) -> None:
        if not enabled or not isinstance(data, dict) or not data:
            self.hide()
            return
        items = data.get("items") if isinstance(data.get("items"), list) else []
        status = str(data.get("status") or "missing")
        self.items = items
        self.show()
        day = str(data.get("day") or "")
        suffix = f" · {_month_day(day)}" if day else ""
        self.eyebrow.setText(f"每日简报{suffix}")
        count = int(data.get("item_count") or len(items))
        self.title.setText(
            f"今天值得知道的 {count} 件事" if items
            else ("今天的简报正在生成" if status in {"pending", "running"}
                  else "今天的简报还没生成"))
        updated = str(data.get("updated_at") or data.get("created_at") or "")
        time = updated[11:16] if len(updated) >= 16 else ""
        sources = (f"{int(data.get('source_ok') or 0)} / {int(data.get('source_total') or 0)} 源"
                   if data.get("source_total") else "")
        self.meta.setText(" · ".join(part for part in (
            "部分完成" if status == "partial" else "",
            f"已生成 {time}" if time else "", sources) if part))
        self._clear()
        if not items:
            self.empty.setText(
                data.get("error")
                or ("正在抓取与写摘要，通常半分钟到两分钟。" if status in {"pending", "running"}
                    else "今天还没有简报，去简报页生成一份。"))
            self.empty.show()
            return
        self.empty.hide()
        lead = BriefLead(items[0], self._navigate)
        self.lead = lead
        self.body.addWidget(lead, 3)
        side = QtWidgets.QVBoxLayout()
        side.setSpacing(0)
        for item in items[1:4]:
            row = BriefRow(item, self._navigate)
            self.rows.append(row)
            side.addWidget(row)
        side.addStretch(1)
        self.body.addLayout(side, 2)

    def _clear(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    child = layout.takeAt(0)
                    node = child.widget()
                    if node is not None:
                        node.setParent(None)
                        node.deleteLater()
        self.rows = []
        self.lead = None


def _month_day(text: str) -> str:
    parts = str(text or "").split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{int(parts[1])} 月 {int(parts[2])} 日"
    return ""


