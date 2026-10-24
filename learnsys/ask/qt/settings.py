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
from . import tokens as token_source
from .memory import SettingsMemoryMixin
from .page import SettingsPageMixin
from .widgets import StatusLabel


# R3.3 可编辑的核心字段；数据目录、记忆、模块、动作按钮各自在后续步骤放开
CORE_FIELDS = frozenset({
    "agent-base", "agent-token", "agent-model", "agent-fast", "agent-strong",
    "agent-auto-route", "agent-tokens", "agent-speed",
    "price-input", "price-output", "price-cache", "price-currency",
    "vision-base", "vision-key", "vision-model",
    "hotkey",
})


def key_hint(has: bool, mask: str, source: str) -> str:
    """和 `web/js/pages/settings.js::keyHint` 同一口径。"""
    if not has:
        return "未配置"
    where = "来自环境变量" if source == "env" else "已保存在设置文件"
    return f"{where}：{mask or '••••'}（留空不改）"


class SettingsWindow(SettingsPageMixin, SettingsMemoryMixin, QtWidgets.QDialog):
    """非模态设置窗口；关掉不影响主程序。"""

    def __init__(self, api, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.api = api
        if isinstance(api, QtCore.QObject):
            api.setParent(self)

        self._base_title = f"设置（Qt 试点）· {product.PRODUCT_NAME}"
        self.setObjectName("SettingsWindow")
        self.setWindowTitle(self._base_title)
        self.tokens = style.apply_theme(self)   # 默认深色：令牌来自 web/css/tokens.css
        self.resize(*style.WINDOW_SIZE)
        self.setMinimumSize(*style.WINDOW_MIN)

        self.inputs: dict[str, QtWidgets.QWidget] = {}
        self.module_boxes: dict[str, QtWidgets.QCheckBox] = {}
        self.memory_rows: dict[int, dict] = {}
        self._settings: dict = {}
        self._modules: list[dict] = []
        self._dirty = False
        self._saving = False
        self._loading = False

        outer = QtWidgets.QGridLayout(self)
        pad = token_source.px(self.tokens, "--s5", 24)
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(0)

        # 版心：内容列最大 780，居中（对齐 Web 的 .settings-page）
        column_widget = QtWidgets.QWidget()
        column_widget.setObjectName("SettingsColumn")
        self.column_widget = column_widget
        column_widget.setMaximumWidth(style.CONTENT_MAX)
        column_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                    QtWidgets.QSizePolicy.Policy.Expanding)
        column = QtWidgets.QVBoxLayout(column_widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(token_source.px(self.tokens, "--s3", 12))
        outer.addWidget(column_widget, 0, 1)
        outer.setColumnStretch(0, 1)
        outer.setColumnStretch(1, 100)
        outer.setColumnStretch(2, 1)
        outer.setRowStretch(0, 1)

        title = QtWidgets.QLabel(f"{product.PRODUCT_NAME} · 设置（Qt 试点）")
        title.setObjectName("PageTitle")
        column.addWidget(title)

        self.status_label = StatusLabel("正在连接后台…")
        self.retry_button = QtWidgets.QPushButton("重试")
        self.retry_button.clicked.connect(self.load)
        self.retry_button.hide()
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.status_label, 1)
        top.addWidget(self.retry_button)
        column.addLayout(top)

        self._build_page(column)
        self._build_actions(column)

        self.api.ready.connect(self._on_ready)
        self.api.failed.connect(self._on_failed)
        self.save_button.clicked.connect(self.save)
        self.test_text_button.clicked.connect(lambda: self.test_connection("text"))
        self.test_vision_button.clicked.connect(lambda: self.test_connection("vision"))
        self.backup_button.clicked.connect(self.backup)
        self.memory_add_button.clicked.connect(self.add_memory)
        self.memory_input.returnPressed.connect(self.add_memory)
        self.set_editable(CORE_FIELDS)   # R3.3：核心表单可改；其余步骤再放开
        self.save_button.setEnabled(True)
        self._wire_dirty()
        # 模块留给 R3.7 放开
        self.memory_list.setEnabled(True)

    # ---- 加载 ----

    def load(self) -> None:
        """每次打开都重新拉：避免显示上次的旧值（R3.8）。"""
        self.set_dirty(False)
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
        self._loading = True              # 程序回填不算用户改动
        try:
            self._apply_settings(self._settings)
        finally:
            self._loading = False

    def _apply_settings(self, data: dict) -> None:
        agent = data.get("agent") or {}
        vision = data.get("vision") or {}

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

        self._loading = True              # 建控件/回填勾选不算用户改动
        try:
            while self.module_layout.count():
                item = self.module_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.module_boxes.clear()

            for index, module in enumerate(self._modules):
                module_id = str(module.get("id") or "")
                if not module_id:
                    continue
                label = str(module.get("name") or module_id)
                if module.get("status") == "planned":
                    label += "（待建）"
                box = QtWidgets.QCheckBox(label)
                box.setProperty("module_id", module_id)
                box.toggled.connect(self.mark_dirty)
                self.module_layout.addWidget(box, index // 2, index % 2)
                self.module_boxes[module_id] = box
            self._apply_module_checks()
        finally:
            self._loading = False

    def _apply_module_checks(self) -> None:
        saved = self._settings.get("modules") or {}
        for module_id, box in self.module_boxes.items():
            box.setChecked(saved.get(module_id, True) is not False)

    # 记忆 CRUD 在 memory.py

    # ---- 可编辑 / dirty ----

    def set_editable(self, editable: set[str] | frozenset[str]) -> None:
        """只放开点名的那几组；数据目录永远只读。"""
        for key, node in self.inputs.items():
            if key == "data-root":
                continue
            on = key in editable
            if isinstance(node, QtWidgets.QLineEdit):
                node.setReadOnly(not on)
            else:
                node.setEnabled(on)

    def _wire_dirty(self) -> None:
        for key in CORE_FIELDS:
            node = self.inputs.get(key)
            if isinstance(node, QtWidgets.QLineEdit):
                node.textChanged.connect(self.mark_dirty)
            elif isinstance(node, QtWidgets.QComboBox):
                node.currentIndexChanged.connect(self.mark_dirty)

    def mark_dirty(self, *_args) -> None:
        if self._loading or self._dirty:
            return
        self.set_dirty(True)

    def set_dirty(self, dirty: bool) -> None:
        self._dirty = bool(dirty)
        self.setWindowTitle(self._base_title + (" *" if self._dirty else ""))
        if self._dirty:
            if not self._saving:
                self.save_note.setText("有改动还没保存")
        else:
            self.save_note.setText("")

    def _value(self, key: str) -> str:
        node = self.inputs.get(key)
        if isinstance(node, QtWidgets.QLineEdit):
            return node.text().strip()
        if isinstance(node, QtWidgets.QComboBox):
            return str(node.currentData() or "")
        return ""

    def collect(self) -> dict:
        """对齐 `web/js/pages/settings.js::collect()`：空密钥 / 空数字不进 payload。"""
        agent = {
            "base_url": self._value("agent-base"),
            "model": self._value("agent-model"),
            "fast_model": self._value("agent-fast"),
            "strong_model": self._value("agent-strong"),
            "auto_route": self._value("agent-auto-route") or "off",
            "speed": self._value("agent-speed") or "balanced",
        }
        tokens = self._value("agent-tokens")
        if tokens:
            try:
                value = int(tokens)
            except ValueError:
                pass
            else:
                if value > 0:
                    agent["max_tokens"] = value
        for key, name in (("price-input", "price_input"),
                          ("price-output", "price_output"),
                          ("price-cache", "price_cache_read")):
            raw = self._value(key)
            if raw == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if value >= 0:
                agent[name] = value
        currency = self._value("price-currency")
        if currency:
            agent["currency"] = currency
        token = self._value("agent-token")
        if token:
            agent["auth_token"] = token

        vision = {
            "base_url": self._value("vision-base"),
            "model": self._value("vision-model"),
        }
        vision_key = self._value("vision-key")
        if vision_key:
            vision["api_key"] = vision_key

        modules = {module_id: box.isChecked()
                   for module_id, box in self.module_boxes.items()}
        return {"agent": agent, "vision": vision,
                "hotkey": self._value("hotkey"), "modules": modules}

    def save(self) -> None:
        if self._saving:
            return
        self._saving = True
        self.save_button.setEnabled(False)
        self.save_note.setText("正在保存…")
        self.api.post("/api/settings", self.collect(),
                      self._on_saved, self._on_save_failed)

    def _on_saved(self, result: dict) -> None:
        result = result or {}
        self._saving = False
        self.save_button.setEnabled(True)
        self.inputs["agent-token"].clear()
        self.inputs["vision-key"].clear()
        self.set_dirty(False)
        restart = bool(result.get("restart_required"))
        message = str(result.get("message") or "已保存")
        self.save_note.setText(
            f"{message}（重启学习工作台后生效）" if restart
            else "已保存。文本/视觉模型下一轮对话立即生效。")
        # 重新拉一次：掩码、来源、模块勾选都以服务端为准
        self.api.get("/api/settings", self._fill_settings, self._fetch_failed)

    def _on_save_failed(self, message: str) -> None:
        self._saving = False
        self.save_button.setEnabled(True)
        self.save_note.setText("")
        self.status_label.show_err(message)

    # ---- 测试连接 / 立即备份 ----

    def test_connection(self, kind: str) -> None:
        if self._dirty:
            self.save_note.setText("先保存再测：测试用的是已保存的配置")
            return
        if kind == "vision":
            button, result = self.test_vision_button, self.test_vision_result
        else:
            button, result = self.test_text_button, self.test_text_result
        button.setEnabled(False)
        result.show_info("测试中…")

        def done(data: dict) -> None:
            button.setEnabled(True)
            data = data or {}
            message = str(data.get("message") or ("可用" if data.get("ok") else "不可用"))
            if data.get("ok"):
                result.show_ok(message)
            else:
                result.show_err(message)

        def failed(message: str) -> None:
            button.setEnabled(True)
            result.show_err(message)

        self.api.post("/api/settings/test", {"kind": kind}, done, failed)

    def backup(self) -> None:
        self.backup_button.setEnabled(False)
        self.backup_result.show_info("备份中…")

        def done(data: dict) -> None:
            self.backup_button.setEnabled(True)
            data = data or {}
            self.backup_result.show_ok(str(data.get("message") or "备份完成"))
            if data.get("path"):
                self.last_backup_label.setText(f"最近备份：{data['path']}")

        def failed(message: str) -> None:
            self.backup_button.setEnabled(True)
            self.backup_result.show_err(message)

        self.api.post("/api/settings/backup", {}, done, failed)
