"""Agent 记忆 CRUD（R3.6）。

列表、添加、修改、删除；所有请求都走 `ApiClient`，界面只负责重新拉取。
"""
from __future__ import annotations

from PySide6 import QtWidgets


class SettingsMemoryMixin:
    def _fill_memory(self, data: dict) -> None:
        items = (data or {}).get("items")
        items = items if isinstance(items, list) else []
        self.memory_list.clear()
        self.memory_rows.clear()
        if not items:
            self.memory_list.addItem("还没有记忆。Agent 听到「以后都…」会自动记；也可以手动加。")
            return
        for item in items:
            memory_id = int(item.get("id") or 0)
            if not memory_id:
                continue
            row = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(row)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(8)
            edit = QtWidgets.QLineEdit(str(item.get("content") or ""))
            edit.setMaxLength(500)
            save = QtWidgets.QPushButton("保存")
            remove = QtWidgets.QPushButton("删除")
            layout.addWidget(edit, 1)
            layout.addWidget(save)
            layout.addWidget(remove)

            holder = QtWidgets.QListWidgetItem()
            holder.setSizeHint(row.sizeHint())
            self.memory_list.addItem(holder)
            self.memory_list.setItemWidget(holder, row)

            save.clicked.connect(lambda _checked=False, mid=memory_id: self.update_memory(mid))
            remove.clicked.connect(lambda _checked=False, mid=memory_id: self.delete_memory(mid))
            edit.returnPressed.connect(lambda mid=memory_id: self.update_memory(mid))
            self.memory_rows[memory_id] = {
                "edit": edit, "save": save, "delete": remove, "item": holder}

    def reload_memory(self) -> None:
        self.api.get("/api/memory", self._fill_memory, self._memory_failed)

    def _memory_failed(self, message: str) -> None:
        self.memory_status.show_err(message)

    def add_memory(self) -> None:
        content = self.memory_input.text().strip()
        if not content:
            return
        self.memory_add_button.setEnabled(False)

        def done(data: dict) -> None:
            self.memory_add_button.setEnabled(True)
            self.memory_input.clear()
            self.memory_status.show_ok(str((data or {}).get("message") or "已记住"))
            self.reload_memory()

        def failed(message: str) -> None:
            self.memory_add_button.setEnabled(True)
            self.memory_status.show_err(message)

        self.api.post("/api/memory", {"content": content}, done, failed)

    def update_memory(self, memory_id: int) -> None:
        row = self.memory_rows.get(memory_id)
        if row is None:
            return
        content = row["edit"].text().strip()
        if not content:
            return
        row["save"].setEnabled(False)
        row["delete"].setEnabled(False)

        def done(data: dict) -> None:
            row["save"].setEnabled(True)
            row["delete"].setEnabled(True)
            self.memory_status.show_ok(str((data or {}).get("message") or "已更新"))
            self.reload_memory()

        def failed(message: str) -> None:
            row["save"].setEnabled(True)
            row["delete"].setEnabled(True)
            self.memory_status.show_err(message)

        self.api.post(f"/api/memory/{memory_id}", {"content": content}, done, failed)

    def delete_memory(self, memory_id: int) -> None:
        row = self.memory_rows.get(memory_id)
        if row is None:
            return
        row["save"].setEnabled(False)
        row["delete"].setEnabled(False)

        def done(data: dict) -> None:
            row["save"].setEnabled(True)
            row["delete"].setEnabled(True)
            self.memory_status.show_ok(str((data or {}).get("message") or "已忘掉"))
            self.reload_memory()

        def failed(message: str) -> None:
            row["save"].setEnabled(True)
            row["delete"].setEnabled(True)
            self.memory_status.show_err(message)

        self.api.delete(f"/api/memory/{memory_id}", done, failed)
