"""设置页的控件搭建（R3.2）。

只负责「长什么样」：分组顺序、字段、提示、按钮。
数据填充与动作在 `settings.py`，保持单一落点。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .widgets import FieldRow, Section, StatusLabel


class SettingsPageMixin:
    def _line(self, key: str | None = None, *, password: bool = False,
              placeholder: str = "", max_length: int | None = None,
              validator: QtGui.QValidator | None = None) -> QtWidgets.QLineEdit:
        node = QtWidgets.QLineEdit()
        node.setPlaceholderText(placeholder)
        node.setClearButtonEnabled(True)
        if password:
            node.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
            node.setClearButtonEnabled(False)
        if max_length is not None:
            node.setMaxLength(max_length)
        if validator is not None:
            node.setValidator(validator)
        if key:
            self.inputs[key] = node
        return node

    def _combo(self, key: str, items: list[tuple[str, str]]) -> QtWidgets.QComboBox:
        node = QtWidgets.QComboBox()
        for label, value in items:
            node.addItem(label, value)
        # 只有点中/聚焦后才响应滚轮 —— 否则在滚动页面时会误改选项
        node.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.inputs[key] = node
        return node

    def _build_page(self, outer: QtWidgets.QVBoxLayout) -> None:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(content)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(12)

        self._build_text_section(column)
        self._build_memory_section(column)
        self._build_cost_section(column)
        self._build_vision_section(column)
        self._build_hotkey_section(column)
        self._build_data_section(column)
        self._build_modules_section(column)

        column.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    def _build_text_section(self, column: QtWidgets.QVBoxLayout) -> None:
        section = Section("文本模型",
                          "主对话用的 Anthropic Messages 兼容服务。密钥只保存在本机，"
                          "页面拿不到明文。")
        section.add_widget(FieldRow(
            "服务地址", self._line("agent-base", placeholder="https://api.deepseek.com/anthropic"),
            small="填到 /anthropic 或 /v1 都行"))
        self.agent_token_hint = QtWidgets.QLabel("未配置")
        self.agent_token_hint.setObjectName("Hint")
        token_row = FieldRow("密钥", self._line("agent-token", password=True), small="留空 = 不修改")
        token_row.add_extra(self.agent_token_hint)
        section.add_widget(token_row)
        section.add_widget(FieldRow("主模型", self._line("agent-model"), small="回答与工具调用"))
        section.add_widget(FieldRow("轻量模型", self._line("agent-fast"), small="短任务 / 快速判断"))
        section.add_widget(FieldRow(
            "强模型", self._line("agent-strong", placeholder="例如 deepseek-v4-pro"),
            small="自动路由升级用；空 = 主模型加思考"))
        section.add_widget(FieldRow(
            "自动路由",
            self._combo("agent-auto-route", [
                ("关闭 · 完全按下面的速度档", "off"),
                ("影子 · 只记录建议，不改实际模型", "shadow"),
                ("启用 · 按建议切换模型", "on"),
            ]),
            hint="只影响「平衡」档；手动速度档与手动 routes 优先。影子模式零额外成本。"))
        section.add_widget(FieldRow(
            "回答上限",
            self._line("agent-tokens", validator=QtGui.QIntValidator(64, 131072, self)),
            small="token，默认 8192"))
        speed_row = FieldRow(
            "回答速度",
            self._combo("agent-speed", [
                ("快 · 轻量模型不思考", "fast"),
                ("平衡 · 主模型不思考", "balanced"),
                ("深入 · 主模型思考", "deep"),
            ]),
            hint="「速答」模式永远走最快档；横栏和工作台共用这一档。")
        self.test_text_button = QtWidgets.QPushButton("测试文本连接")
        self.test_text_result = StatusLabel()
        speed_row.add_extra(self.test_text_button)
        speed_row.add_extra(self.test_text_result)
        section.add_widget(speed_row)
        self.text_section = section
        column.addWidget(section)

    def _build_memory_section(self, column: QtWidgets.QVBoxLayout) -> None:
        section = Section(
            "Agent 记忆",
            "你强调过的跨会话规矩（比如「回答用中文」「需要示例代码时用 C」）。"
            "Agent 每轮都会带上；这里也能自己加、改、删。")
        self.memory_list = QtWidgets.QListWidget()
        self.memory_list.setMinimumHeight(90)
        section.add_widget(self.memory_list)
        self.memory_status = StatusLabel()
        section.add_widget(self.memory_status)
        self.memory_input = self._line("memory-input", max_length=500,
                                       placeholder="例如：回答和思考一律用中文")
        self.memory_add_button = QtWidgets.QPushButton("记下来")
        add_row = QtWidgets.QHBoxLayout()
        add_row.addWidget(self.memory_input, 1)
        add_row.addWidget(self.memory_add_button)
        section.add_widget(self._wrap(add_row))
        self.memory_section = section
        column.addWidget(section)

    def _build_cost_section(self, column: QtWidgets.QVBoxLayout) -> None:
        section = Section(
            "成本估算",
            "填每 100 万 token 的单价（按你的服务商账单填）。不填就只统计 token，"
            "不猜价格；运行记录页会按这里的单价估算每次对话的成本。")
        price_validator = QtGui.QDoubleValidator(0.0, 100000.0, 6, self)
        price_validator.setNotation(QtGui.QDoubleValidator.Notation.StandardNotation)
        section.add_widget(FieldRow(
            "输入单价", self._line("price-input", validator=price_validator),
            small="每 100 万 token，缓存未命中"))
        section.add_widget(FieldRow(
            "输出单价", self._line("price-output", validator=price_validator),
            small="每 100 万 token"))
        section.add_widget(FieldRow(
            "缓存命中单价", self._line("price-cache", validator=price_validator),
            small="每 100 万 token，可留空"))
        section.add_widget(FieldRow(
            "币种", self._line("price-currency", max_length=12, placeholder="USD"),
            small="例如 USD / CNY，只用于显示"))
        self.cost_section = section
        column.addWidget(section)

    def _build_vision_section(self, column: QtWidgets.QVBoxLayout) -> None:
        section = Section(
            "视觉模型",
            "DeepSeek 直连不支持图片。这里填一个 OpenAI 兼容的视觉模型，"
            "截图会先转述成文字；不填就退回 OCR。")
        section.add_widget(FieldRow(
            "服务地址",
            self._line("vision-base", placeholder="https://open.bigmodel.cn/api/paas/v4"),
            small="OpenAI 兼容 /v1"))
        self.vision_key_hint = QtWidgets.QLabel("未配置")
        self.vision_key_hint.setObjectName("Hint")
        key_row = FieldRow("密钥", self._line("vision-key", password=True), small="留空 = 不修改")
        key_row.add_extra(self.vision_key_hint)
        section.add_widget(key_row)
        model_row = FieldRow(
            "模型", self._line("vision-model", placeholder="例如 glm-4v-flash"),
            small="例如 glm-4v-flash")
        self.test_vision_button = QtWidgets.QPushButton("测试视觉连接")
        self.test_vision_result = StatusLabel()
        model_row.add_extra(self.test_vision_button)
        model_row.add_extra(self.test_vision_result)
        section.add_widget(model_row)
        self.vision_section = section
        column.addWidget(section)

    def _build_hotkey_section(self, column: QtWidgets.QVBoxLayout) -> None:
        section = Section("快捷栏")
        section.add_widget(FieldRow(
            "框选快捷键", self._line("hotkey", placeholder="Alt+Q"),
            hint="修饰键 + 一个字母 / 数字 / F1–F24，例如 Alt+Q、Ctrl+Shift+F2",
            small="重启后生效"))
        self.hotkey_section = section
        column.addWidget(section)

    def _build_data_section(self, column: QtWidgets.QVBoxLayout) -> None:
        section = Section("数据与备份")
        data_root = self._line("data-root")
        data_root.setReadOnly(True)
        self.settings_path_label = QtWidgets.QLabel("设置在：")
        self.settings_path_label.setObjectName("Hint")
        self.settings_path_label.setWordWrap(True)
        root_row = FieldRow("数据目录", data_root, small="只读展示")
        root_row.add_extra(self.settings_path_label)
        section.add_widget(root_row)

        self.backup_dir_label = QtWidgets.QLabel("备份目录：")
        self.backup_dir_label.setObjectName("Hint")
        self.backup_dir_label.setWordWrap(True)
        self.last_backup_label = QtWidgets.QLabel("最近备份：—")
        self.last_backup_label.setObjectName("Hint")
        self.last_backup_label.setWordWrap(True)
        self.backup_button = QtWidgets.QPushButton("备份现在")
        self.backup_result = StatusLabel()
        backup_row = FieldRow("立即备份", self._wrap_buttons(), small="整包 zip 到旁边")
        backup_row.add_extra(self.backup_result)
        section.add_widget(backup_row)
        section.add_widget(self.backup_dir_label)
        section.add_widget(self.last_backup_label)
        self.data_section = section
        column.addWidget(section)

    def _wrap_buttons(self) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.backup_button)
        row.addStretch(1)
        return holder

    def _build_modules_section(self, column: QtWidgets.QVBoxLayout) -> None:
        section = Section("侧栏模块", "关掉的模块只是不显示在侧栏；数据不会被删。")
        self.module_container = QtWidgets.QWidget()
        self.module_layout = QtWidgets.QGridLayout(self.module_container)
        self.module_layout.setContentsMargins(0, 0, 0, 0)
        self.module_layout.setHorizontalSpacing(24)
        self.module_layout.setVerticalSpacing(6)
        self.module_layout.setColumnStretch(0, 1)
        self.module_layout.setColumnStretch(1, 1)
        section.add_widget(self.module_container)
        self.modules_section = section
        column.addWidget(section)

    @staticmethod
    def _wrap(layout: QtWidgets.QBoxLayout) -> QtWidgets.QWidget:
        holder = QtWidgets.QWidget()
        holder.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return holder

    def _build_actions(self, outer: QtWidgets.QVBoxLayout) -> None:
        row = QtWidgets.QHBoxLayout()
        self.save_button = QtWidgets.QPushButton("保存设置")
        self.save_button.setObjectName("Primary")
        self.save_button.setEnabled(False)
        self.save_note = QtWidgets.QLabel("")
        self.save_note.setObjectName("Hint")
        row.addWidget(self.save_button)
        row.addWidget(self.save_note, 1)
        outer.addLayout(row)
