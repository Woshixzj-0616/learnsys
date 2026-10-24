"""设置窗口（Qt 试点）。

Qt 只是客户端：字段口径、校验、掩码、原子写都在后端
（`learnsys/server/routes_settings.py`），这里不重复实现。

R3.2：三份数据（settings / modules / memory）读进来，先全部只读；
R3.3 起再逐组放开编辑。控件搭建在 `page.py`。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from learnsys import product

from . import style
from .page import SettingsPageMixin
from .widgets import StatusLabel


def key_hint(has: bool, mask: str, source: str) -> str:
    """和 `web/js/pages/settings.js::keyHint` 同一口径。"""
    if not has:
        return "未配置"
    where = "来自环境变量" if source == "env" else "已保存在设置文件"
    return f"{where}：{mask or '••••'}（留空不改）"


class SettingsWindow(SettingsPageMixin, QtWidgets.QDialog):
    """非模态设置窗口；关掉不影响主程序。"""

    def __init__(self, api, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.api = api
        if isinstance(api, QtCore.QObject):
            api.setParent(self)

        self.setObjectName("SettingsWindow")
        self.setWindowTitle(f"设置（Qt 试点）· {product.PRODUCT_NAME}")
        self.setStyleSheet(style.QSS)
        self.resize(820, 680)
        self.setMinimumSize(620, 420)

        self.inputs: dict[str, QtWidgets.QWidget] = {}
        self.module_boxes: dict[str, QtWidgets.QCheckBox] = {}
        self._settings: dict = {}
        self._modules: list[dict] = []
        self._readonly = True

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        title = QtWidgets.QLabel(f"{product.PRODUCT_NAME} · 设置（Qt 试点）")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        self.status_label = StatusLabel("正在连接后台…")
        self.retry_button = QtWidgets.QPushButton("重试")
        self.retry_button.clicked.connect(self.load)
        self.retry_button.hide()
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.status_label, 1)
        top.addWidget(self.retry_button)
        outer.addLayout(top)

        self._build_page(outer)
        self._build_actions(outer)

        self.api.ready.connect(self._on_ready)
        self.api.failed.connect(self._on_failed)
        self.set_readonly(True)          # R3.2：整页先只读；R3.3 再按组放开

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
        self._fetch_all()

    def _on_failed(self, message: str) -> None:
        self.status_label.show_err(message)
        self.retry_button.show()

    def _fetch_all(self) -> None:
        self.api.get("/api/settings", self._fill_settings, self._fetch_failed)
        self.api.get("/api/modules", self._fill_modules, self._fetch_failed)
        self.api.get("/api/memory", self._fill_memory, self._fetch_failed)

    def _fetch_failed(self, message: str) -> None:
        self.status_label.show_err(f"设置没读出来：{message}")

    # ---- 填充 ----

    def _set(self, key: str, value) -> None:
        node = self.inputs.get(key)
        if node is None:
            return
        if isinstance(node, QtWidgets.QComboBox):
            index = node.findData(str(value or ""))
            node.setCurrentIndex(index if index >= 0 else 0)
        elif isinstance(node, QtWidgets.QLineEdit):
            node.setText("" if value is None else str(value))

    def _fill_settings(self, data: dict) -> None:
        self._settings = data or {}
        agent = self._settings.get("agent") or {}
        vision = self._settings.get("vision") or {}

        self._set("agent-base", agent.get("base_url"))
        self._set("agent-model", agent.get("model"))
        self._set("agent-fast", agent.get("fast_model"))
        self._set("agent-strong", agent.get("strong_model"))
        self._set("agent-auto-route", agent.get("auto_route") or "off")
        self._set("agent-tokens", agent.get("max_tokens"))
        self._set("agent-speed", agent.get("speed") or "balanced")
        self._set("price-input", agent.get("price_input"))
        self._set("price-output", agent.get("price_output"))
        self._set("price-cache", agent.get("price_cache_read"))
        self._set("price-currency", agent.get("currency") or "USD")

        self.inputs["agent-token"].clear()
        self.agent_token_hint.setText(key_hint(
            agent.get("auth_token_set"), agent.get("auth_token_mask"),
            agent.get("auth_token_source")))

        self._set("vision-base", vision.get("base_url"))
        self._set("vision-model", vision.get("model"))
        self.inputs["vision-key"].clear()
        self.vision_key_hint.setText(key_hint(
            vision.get("api_key_set"), vision.get("api_key_mask"),
            vision.get("api_key_source")))

        self._set("hotkey", self._settings.get("hotkey"))
        self._set("data-root", self._settings.get("data_root"))
        self.settings_path_label.setText(f"设置在：{self._settings.get('settings_path') or ''}")
        self.backup_dir_label.setText(f"备份目录：{self._settings.get('backup_dir') or ''}")
        self._apply_module_checks()

    def _fill_modules(self, data: dict) -> None:
        modules = (data or {}).get("modules")
        self._modules = modules if isinstance(modules, list) else []

        while self.module_layout.count():
            item = self.module_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.module_boxes.clear()

        for module in self._modules:
            module_id = str(module.get("id") or "")
            if not module_id:
                continue
            label = str(module.get("name") or module_id)
            if module.get("status") == "planned":
                label += "（待建）"
            box = QtWidgets.QCheckBox(label)
            box.setProperty("module_id", module_id)
            box.setEnabled(not self._readonly)
            self.module_layout.addWidget(box)
            self.module_boxes[module_id] = box
        self.module_layout.addStretch(1)
        self._apply_module_checks()

    def _apply_module_checks(self) -> None:
        saved = self._settings.get("modules") or {}
        for module_id, box in self.module_boxes.items():
            box.setChecked(saved.get(module_id, True) is not False)

    def _fill_memory(self, data: dict) -> None:
        items = (data or {}).get("items")
        items = items if isinstance(items, list) else []
        self.memory_list.clear()
        if not items:
            self.memory_list.addItem("还没有记忆。Agent 听到「以后都…」会自动记；也可以手动加。")
            return
        for item in items:
            self.memory_list.addItem(str(item.get("content") or ""))

    # ---- 只读 / 可编辑 ----

    def set_readonly(self, readonly: bool) -> None:
        """R3.2 全只读；R3.3 起逐组放开时改这里的分组。"""
        self._readonly = bool(readonly)
        for key, node in self.inputs.items():
            if key == "data-root":
                continue                       # 数据目录永远只读
            if isinstance(node, QtWidgets.QLineEdit):
                node.setReadOnly(self._readonly)
            else:
                node.setEnabled(not self._readonly)
        self.memory_list.setEnabled(not self._readonly)
        self.memory_input.setEnabled(not self._readonly)
        self.memory_add_button.setEnabled(not self._readonly)
        self.test_text_button.setEnabled(not self._readonly)
        self.test_vision_button.setEnabled(not self._readonly)
        self.backup_button.setEnabled(not self._readonly)
        for box in self.module_boxes.values():
            box.setEnabled(not self._readonly)
