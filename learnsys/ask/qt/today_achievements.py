"""今日成就：可折叠的一行。

只负责长什么样；数据在 `today.py`。样式走 QSS。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .today_widgets import ClickableCard, _label


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
        self.dot = _label("√" if self.earned else "·", "AchDot")
        self.name = _label(str(item.get("name") or ""), "AchName")
        self.progress = _label(
            f"{int(item.get('value') or 0)}/{int(item.get('target') or 0)}",
            "AchProgress")
        row.addWidget(self.dot, 0)
        row.addWidget(self.name, 1)
        row.addWidget(self.progress, 0)


class CollapsibleAchievements(QtWidgets.QWidget):
    """成就卡：默认折成一行，点开才列出条目。"""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AchievementsCard")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.items: list[AchievementRow] = []

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = ClickableCard()
        self.header.setObjectName("AchHeader")
        head = QtWidgets.QHBoxLayout(self.header)
        head.setContentsMargins(14, 12, 14, 12)
        head.setSpacing(10)
        head.addWidget(_label("成就", "PanelTitle"), 0)
        self.summary = _label("0 / 0", "AchSummary")
        head.addWidget(self.summary, 1, QtCore.Qt.AlignmentFlag.AlignRight)
        self.chev = _label("›", "AchChev")
        head.addWidget(self.chev, 0)
        outer.addWidget(self.header)

        self.body = QtWidgets.QWidget()
        self.body.setObjectName("AchBody")
        self.body_box = QtWidgets.QVBoxLayout(self.body)
        self.body_box.setContentsMargins(14, 0, 14, 10)
        self.body_box.setSpacing(0)
        self.body.hide()
        outer.addWidget(self.body)
        self.header.clicked.connect(self.toggle)

    def set_items(self, items: list[dict]) -> None:
        items = [item for item in (items or []) if isinstance(item, dict)]
        earned = [item for item in items if item.get("earned")]
        locked = [item for item in items if not item.get("earned")]
        next_item = locked[0] if locked else None
        text = f"{len(earned)} / {len(items)}"
        if next_item:
            text += (f" · 下一项 {next_item.get('name')}"
                     f" {int(next_item.get('value') or 0)}/{int(next_item.get('target') or 0)}")
        self.summary.setText(text)
        while self.body_box.count():
            node = self.body_box.takeAt(0)
            widget = node.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.items = []
        for item in (earned + locked)[:8]:
            row = AchievementRow(item)
            self.items.append(row)
            self.body_box.addWidget(row)
        self.body.hide()
        self.chev.setText("›")

    def toggle(self) -> None:
        show = self.body.isHidden()
        self.body.setVisible(show)
        self.chev.setText("⌄" if show else "›")


