"""试点窗口用的小控件：分组、字段行、状态标签。

只做 Qt Widgets，不引入 QML；样式集中在 `style.py`。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from . import style
from . import tokens as token_source


class StatusLabel(QtWidgets.QLabel):
    """一行状态文字：普通提示 / 成功 / 失败。颜色靠动态属性 `state`。"""

    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("Status")
        self.setWordWrap(True)

    def show_info(self, text: str) -> None:
        self._set("info", text)

    def show_ok(self, text: str) -> None:
        self._set("ok", text)

    def show_err(self, text: str) -> None:
        self._set("err", text)

    def _set(self, state: str, text: str) -> None:
        self.setProperty("state", state)
        self.setText(text)
        style = self.style()
        style.unpolish(self)
        style.polish(self)


class Section(QtWidgets.QWidget):
    """一个设置分组：标题、说明、内容区。内容用 `section.body` 往里加。"""

    def __init__(self, title: str, hint: str = "",
                 parent: QtWidgets.QWidget | None = None,
                 tokens: dict[str, str] | None = None):
        super().__init__(parent)
        self.setObjectName("Section")
        # 自定义 QWidget 默认不画 QSS 背景，必须显式打开
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        values = token_source.merged(tokens)
        pad = token_source.px(values, "--s4", 16)
        gap = token_source.px(values, "--s2", 8)
        row_gap = token_source.px(values, "--s3", 12)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(gap)

        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        outer.addWidget(self.title_label)

        self.hint_label = None
        if hint:
            self.hint_label = QtWidgets.QLabel(hint)
            self.hint_label.setObjectName("Hint")
            self.hint_label.setWordWrap(True)
            outer.addWidget(self.hint_label)

        self.body = QtWidgets.QVBoxLayout()
        self.body.setContentsMargins(0, 2, 0, 0)
        self.body.setSpacing(row_gap)
        outer.addLayout(self.body)

    def add_widget(self, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        self.body.addWidget(widget)
        return widget


class FieldRow(QtWidgets.QWidget):
    """一行字段：左侧 label（可带小字说明），右侧控件，下面提示文字。

    `add_extra()` 往控件下方追加一排（例如「测试连接」+ 结果）。
    """

    def __init__(self, label: str, control: QtWidgets.QWidget,
                 hint: str = "", small: str = "",
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.control = control

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(style.FIELD_HSPACE)
        grid.setVerticalSpacing(style.FIELD_GAP)
        grid.setColumnMinimumWidth(0, style.LABEL_MIN)

        label_box = QtWidgets.QVBoxLayout()
        label_box.setContentsMargins(0, 0, 0, 0)
        label_box.setSpacing(2)
        name = QtWidgets.QLabel(label)
        name.setObjectName("FieldLabel")
        name.setContentsMargins(0, 7, 0, 0)   # 对齐 Web `.setting-label { padding-top: 7px }`
        label_box.addWidget(name)
        if small:
            note = QtWidgets.QLabel(small)
            note.setObjectName("Small")
            note.setWordWrap(True)
            label_box.addWidget(note)
        label_box.addStretch(1)
        grid.addLayout(label_box, 0, 0, 2, 1)

        grid.addWidget(control, 0, 1)

        self.hint_label = None
        if hint:
            self.hint_label = QtWidgets.QLabel(hint)
            self.hint_label.setObjectName("Hint")
            self.hint_label.setWordWrap(True)
            grid.addWidget(self.hint_label, 1, 1)

        self.extra = QtWidgets.QHBoxLayout()
        self.extra.setContentsMargins(0, 0, 0, 0)
        self.extra.setSpacing(8)
        self.extra.addStretch(1)          # 尾随弹簧：按钮保持自然宽度，不被拉满
        grid.addLayout(self.extra, 2, 1)
        grid.setColumnStretch(1, 1)

    def add_extra(self, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        self.extra.insertWidget(self.extra.count() - 1, widget)
        return widget

    def set_hint(self, text: str) -> None:
        if self.hint_label is not None:
            self.hint_label.setText(text)
