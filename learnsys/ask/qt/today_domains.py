"""今日页三域卡（Qt）：学习 / 工作 / 生活。

入口 href 由 `/api/home` 下发，Web 与 Qt 读同一份；
这里只做「数据 → 三行文字」的映射和控件，不另算业务口径。
"""
from __future__ import annotations

from PySide6 import QtWidgets

from .today_widgets import ClickableCard, _click_through


def _short(value, limit: int = 40) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] + "…" if len(text) > limit else text


def domain_rows(home: dict | None) -> list[dict]:
    """三域卡的固定顺序与文案；空数据也返回三张卡（显示暂无）。"""
    home = home if isinstance(home, dict) else {}
    learning = home.get("learning") or {}
    work = home.get("work") or {}
    life = home.get("life") or {}
    wrong = (learning.get("recent_wrong") or [{}])[0]
    projects = work.get("projects") or []
    next_step = str(work.get("next_step") or "") or next(
        (str(item.get("next_step") or "") for item in projects
         if item.get("next_step")), "")
    reminders = life.get("reminders") or []
    question = _short(wrong.get("question"))
    return [
        {
            "key": "learn", "label": "学习",
            "href": str(learning.get("href") or "#/cet6"),
            "title": f"今日 {int(learning.get('done') or 0)}"
                     f"/{int(learning.get('total') or 3)}"
                     f" · 到期复习 {int(learning.get('due_reviews') or 0)}",
            "sub": f"最近卡点：{question}" if question else "最近卡点：暂无",
        },
        {
            "key": "work", "label": "工作",
            "href": str(work.get("href") or "#/agents"),
            "title": f"进行中 {int(work.get('running') or 0)}"
                     f" · 待排队 {int(work.get('queued') or 0)}",
            "sub": f"下一步：{_short(next_step)}" if next_step else "下一步：暂无",
        },
        {
            "key": "life", "label": "生活",
            "href": str(life.get("href") or "#/life"),
            "title": f"待办 {int(life.get('item_count') or 0)}"
                     f" · 卡片 {int(life.get('card_count') or 0)}",
            "sub": (f"提醒：{_short(reminders[0])}" if reminders
                    else "提醒：暂无"),
        },
    ]


class DomainCard(ClickableCard):
    """一张三域卡：标签 + 一行状态 + 一行提醒。"""

    def __init__(self, navigate, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DomainCard")
        self._navigate = navigate or (lambda _href: None)
        self.key = ""
        self.href = ""
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 13)
        box.setSpacing(2)
        self.label = QtWidgets.QLabel("", self)
        self.label.setObjectName("DomainLabel")
        self.title = QtWidgets.QLabel("", self)
        self.title.setObjectName("DomainTitle")
        self.sub = QtWidgets.QLabel("", self)
        self.sub.setObjectName("DomainSub")
        for node in (self.title, self.sub):
            node.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                               QtWidgets.QSizePolicy.Policy.Preferred)
        box.addWidget(self.label)
        box.addWidget(self.title)
        box.addWidget(self.sub)
        self.clicked.connect(self._open)
        _click_through(self)

    def _open(self) -> None:
        if self.href:
            self._navigate(self.href)

    def set_row(self, row: dict) -> None:
        self.key = str(row.get("key") or "")
        self.href = str(row.get("href") or "")
        self.label.setText(str(row.get("label") or ""))
        self.title.setText(str(row.get("title") or "暂无"))
        self.sub.setText(str(row.get("sub") or "暂无"))
        self.setAccessibleName(f"{self.label.text()}：{self.title.text()}")


class DomainGrid(QtWidgets.QWidget):
    """三张卡一行；入口与 Web 的 `domain-grid` 一一对应。"""

    def __init__(self, navigate, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DomainGrid")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.cards: dict[str, DomainCard] = {}
        for key in ("learn", "work", "life"):
            card = DomainCard(navigate)
            self.cards[key] = card
            row.addWidget(card, 1)
        self.set_data(None)

    def set_data(self, home: dict | None) -> None:
        for row, card in zip(domain_rows(home), self.cards.values()):
            card.set_row(row)
