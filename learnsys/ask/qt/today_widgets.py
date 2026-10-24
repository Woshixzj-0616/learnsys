"""今日页的原生控件（R4）：Hero、统计条、行动卡、插件卡、首次提示。

只负责长什么样；数据和跳转在 `today.py`。样式仍集中在 `style.py` 的 QSS 模板。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


def minutes_parts(minutes) -> tuple[str, str]:
    """和 `web/js/ui.js::minutesParts` 同口径。"""
    total = max(0, int(round(float(minutes or 0))))
    if total < 60:
        return str(total), "分钟"
    hours, rest = divmod(total, 60)
    return (f"{hours} 时 {rest}" if rest else str(hours),
            "分" if rest else "小时")


def chars_parts(chars) -> tuple[str, str]:
    total = max(0, float(chars or 0))
    if total < 10000:
        return str(int(total)), "字"
    return f"{total / 10000:.1f}", "万字"


def _label(text: str = "", name: str = "") -> QtWidgets.QLabel:
    node = QtWidgets.QLabel(text)
    if name:
        node.setObjectName(name)
    return node


def _click_through(widget: QtWidgets.QWidget) -> None:
    """卡片里的文字不抢鼠标，点哪儿都算点卡片。"""
    for child in widget.findChildren(QtWidgets.QWidget):
        child.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


class ClickableCard(QtWidgets.QWidget):
    """可点击卡片：鼠标、回车、空格都能触发；hover/焦点样式走 QSS。"""

    clicked = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if (event.button() == QtCore.Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter,
                           QtCore.Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class GoalBar(QtWidgets.QProgressBar):
    """0–100% 的细进度条；值按千分之一存，避免整数截断。"""

    def __init__(self, name: str, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(name)
        self.setTextVisible(False)
        self.setRange(0, 1000)
        self.setValue(0)
        self.setFixedHeight(9)


class HeroCard(QtWidgets.QWidget):
    """今日 Hero：问候/主标题/目标进度 + 连续天数/等级。"""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("HeroCard")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(28, 26, 28, 26)
        outer.setSpacing(28)

        main = QtWidgets.QVBoxLayout()
        main.setSpacing(8)
        self.eyebrow = _label("今日", "Eyebrow")
        self.title = _label("今天，练一格。", "HeroTitle")
        self.title.setWordWrap(True)
        self.subtitle = _label(
            "问出去、听清楚、抓包看明白 —— 每天留下一点能看见的进度。", "HeroSub")
        self.subtitle.setWordWrap(True)
        main.addWidget(self.eyebrow)
        main.addWidget(self.title)
        main.addWidget(self.subtitle)
        main.addSpacing(10)

        goal_head = QtWidgets.QHBoxLayout()
        goal_label = _label("今日学习点", "GoalHead")
        self.goal_text = _label("0 / 100", "GoalText")
        goal_head.addWidget(goal_label)
        goal_head.addStretch(1)
        goal_head.addWidget(self.goal_text)
        main.addLayout(goal_head)

        self.goal_bar = GoalBar("GoalBar")
        main.addWidget(self.goal_bar)
        self.goal_note = _label("问答 10 · 转写 5 · 六级断点 8 · 专注 1 分钟 1", "GoalNote")
        self.goal_note.setWordWrap(True)
        main.addWidget(self.goal_note)
        main.addStretch(1)
        outer.addLayout(main, 1)

        side_widget = QtWidgets.QWidget()
        side_widget.setFixedWidth(300)
        side = QtWidgets.QVBoxLayout(side_widget)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(12)

        streak = QtWidgets.QWidget()
        streak.setObjectName("SideCard")
        streak.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        streak_row = QtWidgets.QHBoxLayout(streak)
        streak_row.setContentsMargins(16, 14, 16, 14)
        streak_row.setSpacing(8)
        flame = _label("▲", "StreakFlame")
        self.streak_value = _label("0", "StreakNum")
        streak_text = _label("天连续学习", "StreakLabel")
        streak_row.addWidget(flame)
        streak_row.addWidget(self.streak_value)
        streak_row.addWidget(streak_text)
        streak_row.addStretch(1)
        side.addWidget(streak)

        level = QtWidgets.QWidget()
        level.setObjectName("SideCard")
        level.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        level_box = QtWidgets.QVBoxLayout(level)
        level_box.setContentsMargins(16, 14, 16, 14)
        level_box.setSpacing(8)
        level_line = QtWidgets.QHBoxLayout()
        level_line.setSpacing(8)
        self.level_badge = _label("Lv.1", "LevelBadge")
        self.level_title = _label("网络小白", "LevelTitle")
        level_line.addWidget(self.level_badge)
        level_line.addWidget(self.level_title)
        level_line.addStretch(1)
        level_box.addLayout(level_line)
        self.level_bar = GoalBar("LevelBar")
        self.level_bar.setFixedHeight(6)
        level_box.addWidget(self.level_bar)
        self.level_note = _label("再攒 300 学习点升级", "SideNote")
        self.level_note.setWordWrap(True)
        level_box.addWidget(self.level_note)
        side.addWidget(level)
        side.addStretch(1)
        outer.addWidget(side_widget, 0)

    def update_overview(self, overview: dict) -> None:
        today = overview.get("today") or {}
        total = overview.get("total") or {}
        streak = int(overview.get("streak") or 0)
        name = str(overview.get("name") or "").strip()
        hour = QtCore.QTime.currentTime().hour()
        part = ("夜深了" if hour < 6 else "早上好" if hour < 11
                else "中午好" if hour < 14 else "下午好" if hour < 18 else "晚上好")
        self.eyebrow.setText(f"{part}，{name}" if name else part)

        percent = float(today.get("percent") or 0)
        if percent >= 100:
            self.title.setText("今日目标达成。")
            self.subtitle.setText("学习点已经攒够 —— 想再往前走，去训练场开一格。")
        elif streak >= 7:
            self.title.setText(f"连续 {streak} 天，稳住。")
            self.subtitle.setText("把今天的目标收掉，就是给这条连续线续命。")
        else:
            self.title.setText("今天，练一格。")
            self.subtitle.setText("问出去、听清楚、抓包看明白 —— 每天留下一点能看见的进度。")

        xp = int(today.get("xp") or 0)
        goal = int(today.get("goal") or 100)
        self.goal_text.setText(f"{xp} / {goal}")
        self.goal_bar.setValue(int(round(min(percent, 100) * 10)))
        left = max(0, goal - xp)
        self.goal_note.setText(
            f"再攒 {left} 学习点到今天的目标" if left else "今天的目标已经完成，继续保持")

        self.streak_value.setText(str(streak))
        self.level_badge.setText(f"Lv.{total.get('level') or 1}")
        self.level_title.setText(str(total.get("title") or "网络小白"))
        self.level_bar.setValue(int(round(float(total.get("percent") or 0) * 10)))
        need = max(0, int(total.get("need") or 0) - int(total.get("into") or 0))
        self.level_note.setText(
            f"累计 {int(total.get('xp') or 0)} 点 · 再攒 {need} 点升级")


class StatCell(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StatCell")
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(18, 15, 18, 13)
        box.setSpacing(2)
        self.label = _label("", "StatLabel")
        box.addWidget(self.label)
        value_row = QtWidgets.QHBoxLayout()
        value_row.setSpacing(3)
        self.value = _label("0", "StatValue")
        self.unit = _label("", "StatUnit")
        value_row.addWidget(self.value)
        value_row.addWidget(self.unit, 0, QtCore.Qt.AlignmentFlag.AlignBottom)
        value_row.addStretch(1)
        box.addLayout(value_row)
        self.note = _label("", "StatNote")
        self.note.setWordWrap(True)
        box.addWidget(self.note)

    def update(self, item: dict) -> None:
        self.label.setText(str(item.get("label") or ""))
        self.value.setText(str(item.get("value") or ""))
        self.unit.setText(str(item.get("unit") or ""))
        self.note.setText(str(item.get("note") or ""))


class StatStrip(QtWidgets.QWidget):
    """四格统计条：一个外框 + 三条分隔线。"""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StatStrip")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.cells: list[StatCell] = []
        for index in range(4):
            if index:
                sep = QtWidgets.QWidget()
                sep.setObjectName("StatSep")
                sep.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
                sep.setFixedWidth(1)
                row.addWidget(sep)
            cell = StatCell()
            self.cells.append(cell)
            row.addWidget(cell, 1)

    def update_stats(self, items: list[dict]) -> None:
        for index, cell in enumerate(self.cells):
            cell.update(items[index] if index < len(items) else {})


class ActionCard(ClickableCard):
    def __init__(self, item: dict, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ActionCard")
        self.href = str(item.get("href") or "")
        self.setAccessibleName(str(item.get("title") or "行动"))
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(14, 14, 16, 14)
        row.setSpacing(12)
        self.number_label = _label("1", "ActionNo")
        self.number_label.setFixedSize(22, 22)
        self.number_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.number_label, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        main = QtWidgets.QVBoxLayout()
        main.setSpacing(3)
        title = _label(str(item.get("title") or ""), "CardTitle")
        title.setWordWrap(True)
        detail = _label(str(item.get("detail") or ""), "CardDetail")
        detail.setWordWrap(True)
        main.addWidget(title)
        main.addWidget(detail)
        row.addLayout(main, 1)

        label = _label(str(item.get("label") or "去看看") + " →", "CardLabel")
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                           | QtCore.Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(label, 0)
        _click_through(self)

    def set_number(self, number: int) -> None:
        self.number_label.setText(str(number))


class PluginCard(ClickableCard):
    def __init__(self, module: dict, count: str,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PluginCard")
        self.href = f"#/{module.get('id') or ''}"
        self.setMinimumWidth(230)
        self.setMinimumHeight(108)
        self.setAccessibleName(str(module.get("name") or "插件"))
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(16, 16, 17, 16)
        box.setSpacing(7)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)
        icon = _label(str(module.get("icon") or "·"), "PluginIcon")
        icon.setFixedSize(34, 34)
        icon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        name = _label(str(module.get("name") or ""), "PluginName")
        category = _label(str(module.get("category") or "插件"), "PluginCat")
        category.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                              | QtCore.Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(icon)
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(category)
        box.addLayout(top)

        tagline = _label(str(module.get("tagline") or module.get("note") or ""),
                         "CardDetail")
        tagline.setWordWrap(True)
        box.addWidget(tagline, 1)

        foot_widget = QtWidgets.QWidget()
        foot_widget.setObjectName("PluginFoot")
        foot_widget.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        foot = QtWidgets.QHBoxLayout(foot_widget)
        foot.setContentsMargins(0, 9, 0, 0)
        foot.setSpacing(0)
        foot.addWidget(_label(count or "打开", "PluginCount"))
        foot.addStretch(1)
        foot.addWidget(_label("进入 →", "PluginOpen"))
        box.addWidget(foot_widget)
        _click_through(self)


class OnboardingBanner(QtWidgets.QWidget):
    """首次使用提示：一行就够，点了去 Qt 设置。"""

    configure = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        text = _label(
            "文本模型还没配好：设置里填服务地址、密钥和模型名，今日页才有数据。",
            "BannerText")
        text.setWordWrap(True)
        row.addWidget(text, 1)
        button = QtWidgets.QPushButton("去配置")
        button.setObjectName("Primary")
        button.clicked.connect(self.configure.emit)
        row.addWidget(button)
        self.hide()
