"""今日页原生控件：Hero、简报横条、接着上次、工作入口、今天一行。

只负责长什么样；数据、跳转与拉取在 `today.py`。
样式仍集中在 `style.py` 的 QSS 模板，颜色只来自 `web/css/tokens.css`。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from . import style
from . import tokens as token_source


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


class GoalRing(QtWidgets.QWidget):
    """今日目标圆环：底环 + 进度弧 + 中间完成数。"""

    def __init__(self, tokens: dict | None = None,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("HeroRing")
        self.setFixedSize(96, 96)
        self.percent = 0.0
        self.label = ""
        self._tokens = token_source.merged(
            tokens if tokens is not None else token_source.read_web_tokens())

    def set_percent(self, percent: float, label: str = "") -> None:
        self.percent = max(0.0, min(100.0, float(percent or 0)))
        self.label = str(label or "")
        self.update()

    def paintEvent(self, _event) -> None:
        values = self._tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = QtCore.QRectF(self.rect()).adjusted(7, 7, -7, -7)

        track = QtGui.QPen(style.color(values["--line"]), 6)
        track.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)

        if self.percent > 0:
            arc = QtGui.QPen(style.color(values["--accent"]), 6)
            arc.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(arc)
            painter.drawArc(rect, 90 * 16, -int(360 * 16 * self.percent / 100))

        painter.setPen(style.color(values["--text"]))
        font = QtGui.QFont(self.font())
        font.setPixelSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(0, -6, 0, -6),
                         QtCore.Qt.AlignmentFlag.AlignCenter,
                         self.label or f"{int(round(self.percent))}%")
        font.setPixelSize(9)
        font.setBold(False)
        painter.setPen(style.color(values["--text-faint"]))
        painter.setFont(font)
        painter.drawText(
            self.rect().adjusted(0, 0, 0, -14),
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignBottom,
            "今日目标")
        painter.end()


class GoalTaskRow(ClickableCard):
    """今日三件事的一行：勾选 + 标题 + 说明 + 分钟 + 去做的入口。"""

    def __init__(self, task: dict, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("GoalTask")
        self.setProperty("done", bool(task.get("done")))
        self.href = str(task.get("href") or "")
        self.setAccessibleName(str(task.get("title") or "今日任务"))
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(10)

        self.check = _label("√" if task.get("done") else "○", "GoalCheck")
        self.check.setFixedWidth(18)
        self.check.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.check, 0)

        body = QtWidgets.QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(1)
        self.title = _label(str(task.get("title") or ""), "GoalTaskTitle")
        self.title.setWordWrap(True)
        self.detail = _label(str(task.get("detail") or ""), "GoalTaskDetail")
        self.detail.setWordWrap(True)
        body.addWidget(self.title)
        body.addWidget(self.detail)
        row.addLayout(body, 1)

        self.minutes = _label(f"{int(task.get('minutes') or 0)} 分钟", "GoalTaskMin")
        row.addWidget(self.minutes, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self.go = _label(f"{task.get('label') or '打开'} →", "GoalTaskGo")
        row.addWidget(self.go, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        _click_through(self)


class HeroCard(QtWidgets.QWidget):
    """今日 Hero：问候 + 徽章 + 状态一句 + 三行任务 + 提问入口 + 圆环。"""

    def __init__(self, tokens: dict | None = None, navigate=None,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("HeroCard")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._navigate = navigate or (lambda _href: None)

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(24, 22, 22, 18)
        outer.setSpacing(22)

        main = QtWidgets.QVBoxLayout()
        main.setSpacing(8)
        self.title = _label("今日", "HeroTitle")
        main.addWidget(self.title)

        meta = QtWidgets.QHBoxLayout()
        meta.setSpacing(8)
        self.level_chip = _label("Lv.1 · 网络小白", "HeroBadge")
        self.streak_chip = _label("连续 0 天", "HeroBadgeMark")
        self.state = _label("", "HeroState")
        self.state.setWordWrap(True)
        meta.addWidget(self.level_chip, 0)
        meta.addWidget(self.streak_chip, 0)
        meta.addWidget(self.state, 1)
        main.addLayout(meta)

        self.tasks_box = QtWidgets.QVBoxLayout()
        self.tasks_box.setSpacing(6)
        main.addLayout(self.tasks_box)
        self.tasks: list[GoalTaskRow] = []

        self.ask = ClickableCard()
        self.ask.setObjectName("HeroAsk")
        self.ask.setFixedHeight(44)
        ask_row = QtWidgets.QHBoxLayout(self.ask)
        ask_row.setContentsMargins(14, 0, 12, 0)
        ask_row.setSpacing(10)
        ask_row.addWidget(_label("问", "HeroAskIcon"), 0)
        ask_row.addWidget(_label("问点什么，或把题目粘进来…", "HeroAskText"), 1)
        ask_row.addWidget(_label("发送", "HeroAskSend"), 0)
        self.ask.clicked.connect(lambda: self._navigate("#/ask"))
        main.addWidget(self.ask)
        outer.addLayout(main, 1)

        ring_box = QtWidgets.QVBoxLayout()
        ring_box.setSpacing(0)
        ring_box.addStretch(1)
        self.ring = GoalRing(tokens)
        ring_box.addWidget(self.ring, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        ring_box.addStretch(1)
        outer.addLayout(ring_box, 0)

    def update_overview(self, overview: dict) -> None:
        today = overview.get("today") or {}
        total = overview.get("total") or {}
        streak = int(overview.get("streak") or 0)
        name = str(overview.get("name") or "").strip()
        hour = QtCore.QTime.currentTime().hour()
        part = ("夜深了" if hour < 6 else "早上好" if hour < 11
                else "中午好" if hour < 14 else "下午好" if hour < 18 else "晚上好")
        self.title.setText(f"{part}，{name}" if name else part)

        tasks = today.get("goal_tasks") or []
        done = int(today.get("goal_done") or 0)
        total_tasks = max(1, int(today.get("goal_total") or len(tasks) or 3))
        tier = str(today.get("goal_tier") or "none")
        if done >= total_tasks:
            state = "三件都做完了 · 今天超额完成"
        elif tier == "met":
            state = "今天已达标 · 第三件复盘是加分"
        elif done > 0:
            state = f"完成 {done} 件 · 再做一件就达标"
        elif streak >= 7:
            state = f"连续 {streak} 天 · 今天先挑一件"
        else:
            state = "做完两件算达标，第三件是加分"
        self.state.setText(state)
        self.streak_chip.setText(f"连续 {streak} 天")
        self.level_chip.setText(
            f"Lv.{total.get('level') or 1} · {total.get('title') or '网络小白'}")
        percent = min(100.0, done * 100.0 / total_tasks)
        self.ring.set_percent(percent, f"{done} / {total_tasks}")

        while self.tasks_box.count():
            item = self.tasks_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.tasks = []
        for task in tasks[:3]:
            row = GoalTaskRow(task)
            row.clicked.connect(lambda r=row: self._navigate(r.href))
            self.tasks.append(row)
            self.tasks_box.addWidget(row)


def _short(text, limit: int) -> str:
    raw = " ".join(str(text or "").split())
    return raw[:limit] + "…" if len(raw) > limit else raw


class AltRow(ClickableCard):
    """「也可以」：主卡下面的备选行动。"""

    def __init__(self, action: dict, navigate, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AltRow")
        self.href = str(action.get("href") or "")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(9)
        row.addWidget(_label("也可以", "AltLabel"), 0)
        row.addWidget(_label(_short(action.get("title"), 34), "AltTitle"), 1)
        row.addWidget(_label(_short(action.get("detail"), 30), "AltMeta"), 0)
        row.addWidget(_label(f"{action.get('label') or '去看看'} →", "AltGo"), 0)
        self.clicked.connect(lambda: navigate(self.href))
        _click_through(self)


class ContinueCard(QtWidgets.QWidget):
    """接着上次：六级断点 + 一个备选行动。"""

    def __init__(self, navigate, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ContinueCard")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self._navigate = navigate or (lambda _href: None)
        self._href = "#/cet6"
        self.alts: list[AltRow] = []

        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(20, 16, 20, 14)
        box.setSpacing(4)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(_label("接着上次", "Eyebrow"), 1)
        head.addWidget(_label("六级训练", "Pill"), 0)
        box.addLayout(head)
        self.title = _label("今天还没练六级", "ContinueTitle")
        self.title.setWordWrap(True)
        box.addWidget(self.title)
        self.sub = _label("精听 / 写作 / 翻译，挑一项开始", "ContinueSub")
        box.addWidget(self.sub)

        stats = QtWidgets.QHBoxLayout()
        stats.setSpacing(14)
        self.count = _label("今天 0 个断点", "ContinueStat")
        self.last = _label("从 25 分钟的微训练开始", "ContinueStat")
        self.state = _label("", "ContinueStat")
        stats.addWidget(self.count)
        stats.addWidget(self.last)
        stats.addWidget(self.state)
        stats.addStretch(1)
        box.addLayout(stats)

        foot = QtWidgets.QHBoxLayout()
        foot.addWidget(_label("每天 25 分钟，比周末补两小时有用", "Hint"), 1)
        self.button = QtWidgets.QPushButton("去训练 →")
        self.button.setObjectName("Primary")
        foot.addWidget(self.button, 0)
        box.addLayout(foot)

        self.alts_box = QtWidgets.QVBoxLayout()
        self.alts_box.setSpacing(0)
        box.addLayout(self.alts_box)
        self.button.clicked.connect(lambda: self._navigate(self._href))

    def set_data(self, items, goal_tasks, actions) -> None:
        item = (items or [{}])[0] if items else {}
        listen_done = any(task.get("id") == "listen" and task.get("done")
                          for task in (goal_tasks or []))
        if item:
            self.title.setText(str(item.get("paper") or "六级训练"))
            self.sub.setText(" · ".join(part for part in (
                str(item.get("section") or ""), str(item.get("item") or "")) if part)
                or "继续上次的训练")
            self.count.setText(f"{int(item.get('count') or 0)} 处断点")
            stamp = str(item.get("last") or "")
            self.last.setText(f"最近 {stamp[11:16]}" if len(stamp) >= 16 else "今天刚记下")
            self.state.setText("今天精听已达标" if listen_done else "今天还没练")
            paper = str(item.get("paper_id") or item.get("paper") or "")
            self._href = "#/cet6?paper=" + _quote(paper)
            self.button.setText("回到断点 →")
        else:
            self.title.setText("今天还没练六级")
            self.sub.setText("精听 / 写作 / 翻译，挑一项开始")
            self.count.setText("今天 0 个断点")
            self.last.setText("从 25 分钟的微训练开始")
            self.state.setText("")
            self._href = "#/cet6"
            self.button.setText("去训练 →")

        while self.alts_box.count():
            node = self.alts_box.takeAt(0)
            widget = node.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.alts = []
        seen = {self._href}
        for action in actions or []:
            href = str(action.get("href") or "")
            if not href or href in seen:
                continue
            seen.add(href)
            row = AltRow(action, self._navigate)
            self.alts.append(row)
            self.alts_box.addWidget(row)
            if len(self.alts) >= 2:
                break


def _quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")


class WorkEntryCard(QtWidgets.QWidget):
    """工作场景入口：只换入口，不改数据。"""

    def __init__(self, navigate, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ContinueCard")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(20, 16, 20, 14)
        box.setSpacing(4)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(_label("工作入口", "Eyebrow"), 1)
        head.addWidget(_label("只读优先", "Pill"), 0)
        box.addLayout(head)
        box.addWidget(_label("把整件事派出去", "ContinueTitle"))
        box.addWidget(_label(
            "Agent 中枢负责执行，浏览器和运行记录都在侧栏。", "ContinueSub"))
        stats = QtWidgets.QHBoxLayout()
        stats.setSpacing(14)
        for text in ("Claude Code", "Codex", "限 D:\\Desktop"):
            stats.addWidget(_label(text, "ContinueStat"))
        stats.addStretch(1)
        box.addLayout(stats)
        foot = QtWidgets.QHBoxLayout()
        foot.addWidget(_label("不接管登录，不静默执行", "Hint"), 1)
        button = QtWidgets.QPushButton("打开中枢 →")
        button.setObjectName("Primary")
        button.clicked.connect(lambda: (navigate or (lambda _href: None))("#/agents"))
        foot.addWidget(button, 0)
        box.addLayout(foot)
        self.hide()


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


class FactsStrip(QtWidgets.QWidget):
    """本周卡底部的今天一行：问答 / 听力断点 / 训练 / 实测专注。"""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("FactsStrip")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(0)
        self.cells: list[tuple[QtWidgets.QLabel, QtWidgets.QLabel]] = []
        for index in range(4):
            if index:
                sep = QtWidgets.QWidget()
                sep.setObjectName("FactSep")
                sep.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
                sep.setFixedWidth(1)
                row.addWidget(sep)
            cell = QtWidgets.QWidget()
            cell.setObjectName("FactCell")
            box = QtWidgets.QVBoxLayout(cell)
            box.setContentsMargins(8, 1, 8, 1)
            box.setSpacing(0)
            value = _label("0", "FactValue")
            label = _label("", "FactLabel")
            box.addWidget(value)
            box.addWidget(label)
            self.cells.append((value, label))
            row.addWidget(cell, 1)

    def set_facts(self, facts: list[dict]) -> None:
        for index, (value, label) in enumerate(self.cells):
            item = facts[index] if index < len(facts) else {}
            unit = str(item.get("unit") or "")
            text = str(item.get("value") or "0")
            value.setText(f"{text} {unit}" if unit else text)
            label.setText(str(item.get("label") or ""))
