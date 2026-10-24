"""设置窗口（Qt 试点）。

R3.1 只证明一件事：窗口能拿到令牌、读到后端版本。
字段渲染从 R3.2 开始填。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from learnsys import product

from . import style
from .widgets import StatusLabel


class SettingsWindow(QtWidgets.QDialog):
    """非模态设置窗口；关掉不影响主程序。"""

    def __init__(self, api, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.api = api
        if isinstance(api, QtCore.QObject):
            api.setParent(self)

        self.setObjectName("SettingsWindow")
        self.setWindowTitle(f"设置（Qt 试点）· {product.PRODUCT_NAME}")
        self.setStyleSheet(style.QSS)
        self.resize(760, 560)
        self.setMinimumSize(560, 360)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QtWidgets.QLabel(f"{product.PRODUCT_NAME} · 设置（Qt 试点）")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.status_label = StatusLabel("正在连接后台…")
        self.retry_button = QtWidgets.QPushButton("重试")
        self.retry_button.clicked.connect(self.load)
        self.retry_button.hide()

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.status_label, 1)
        top.addWidget(self.retry_button)
        layout.addLayout(top)
        layout.addStretch(1)

        self.api.ready.connect(self._on_ready)
        self.api.failed.connect(self._on_failed)

    # ---- 加载 ----

    def load(self) -> None:
        """每次打开都重新拉：避免显示上次的旧值（R3.8）。"""
        self.status_label.show_info("正在连接后台…")
        self.retry_button.hide()
        self.api.start()

    def _on_ready(self) -> None:
        version = f"v{self.api.version}" if self.api.version else "版本未知"
        self.status_label.show_ok(f"已连接：{product.PRODUCT_NAME} {version}")
        self.retry_button.hide()

    def _on_failed(self, message: str) -> None:
        self.status_label.show_err(message)
        self.retry_button.show()
