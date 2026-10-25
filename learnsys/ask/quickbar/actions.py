"""菜单与低频操作：录制菜单、⋯ 菜单、模式、文档、收藏、复制、历史。"""
from __future__ import annotations

import pathlib
import uuid

from PySide6 import QtCore, QtGui, QtWidgets

from .common import (MODE_LABELS, QSS, STATE_DONE, STATE_HISTORY, _answer_char,
                     _gap_block)


class ActionsMixin:
    def _rec_menu(self, pos) -> None:
        """录像按钮右键：暂停/继续 + 定时停止（不用再加按钮占位置）。"""
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(QSS)
        menu.addAction("继续录像" if self.rec_paused else "暂停录像",
                       self.rec_pause_toggled.emit)
        timer_menu = menu.addMenu("定时停止录像")
        for minutes in (30, 45, 60, 90):
            timer_menu.addAction(f"{minutes} 分钟后",
                                 lambda m=minutes: self.rec_timer_set.emit(m))
        timer_menu.addAction("取消定时", lambda: self.rec_timer_set.emit(0))
        menu.exec(self.rec_btn.mapToGlobal(pos))

    def _more_menu(self) -> None:
        """「⋯」收纳菜单：低频操作全在这里，横栏上只留高频按钮。"""
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(QSS)
        mode_menu = menu.addMenu("回答模式")
        for key, label in MODE_LABELS.items():
            action = mode_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.ask_mode == key)
            action.triggered.connect(lambda checked=False, m=key: self._set_mode(m))
        menu.addSeparator()
        menu.addAction("测验（5 道题）", self.quiz_btn.click)
        menu.addAction("历史", self.history_btn.click)
        menu.addSeparator()
        menu.addAction("学习报告（Markdown）", self.report_requested.emit)
        menu.addAction("导出对话笔记", self.notes_requested.emit)
        menu.addAction("导出错题本（Anki CSV）", self.anki_requested.emit)
        menu.addSeparator()
        top = menu.addAction("置顶（横栏一直在最上层）")
        top.setCheckable(True)
        top.setChecked(self._on_top)
        top.triggered.connect(self.top_btn.click)
        menu.addSeparator()
        menu.addAction("清空当前对话", self._clear_with_confirm)
        menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))

    def _set_mode(self, mode: str) -> None:
        """切回答模式：讲解 / 引导 / 测验 / 速答。只影响下一轮，不动当前答案。"""
        if mode not in MODE_LABELS:
            return
        self.ask_mode = mode
        self.quiz_mode = mode == "quiz"
        label = MODE_LABELS[mode]
        self._set_status(f"回答模式：{label}")
        self.ask.setPlaceholderText(f"回答模式：{label} —— 直接打字问")

    def _clear_with_confirm(self) -> None:
        """清空前确认一下（有内容才弹；空界面直接清，不烦人）。"""
        has_content = (bool(self.answer.toPlainText().strip())
                       or self.thumb.isVisible() or bool(self._turns))
        if has_content and not self._confirm_clear():
            return
        self.clear_session()

    def _confirm_clear(self) -> bool:
        """弹确认框，用户点「清空」返回 True。单独拆出来方便测试。"""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("清空")
        box.setText("把当前对话清掉？截图和收藏过的题不受影响，随时能从「历史」再看。")
        yes = box.addButton("清空", QtWidgets.QMessageBox.DestructiveRole)
        cancel = box.addButton("先不清", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is yes

    def set_doc(self, path: str, text: str) -> None:
        """挂载课件文档：之后每次提问都把文档正文一起发给 AI（最多带 6000 字）。"""
        self.doc_path = str(path)
        self.doc_name = pathlib.Path(path).name
        self.doc_text = text[:6000]
        self.ask.setPlaceholderText(f"📄 {self.doc_name} 已挂 —— 直接问它；「清空」摘掉")
        self.show_message(f"已挂文档 {self.doc_name}（截取 {len(self.doc_text)} 字）—— 直接提问就行。")

    def clear_doc(self) -> None:
        had = self.doc_path is not None
        self.doc_path = None
        self.doc_name = ""
        self.doc_text = ""
        if had:
            self.ask.setPlaceholderText(f"直接打字问就行；想问屏幕上的东西就先点「框选」或按 {self._tip}")
            self.show_message("已摘掉文档。")

    def append_text(self, text: str) -> None:
        """往答案区末尾追加一段（电脑助手逐步汇报执行结果用）。"""
        if not self._answer_shown:
            self.set_state(STATE_DONE)      # 没有对话时也把面板亮出来（几何只变这一次）
        cursor = self.answer.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertBlock(_gap_block())
        cursor.insertText(text, _answer_char())
        self._scroll_follow()

    def set_rec_paused(self, paused: bool) -> None:
        self.rec_paused = paused
        if not self._recording:
            return
        if paused:
            self._set_rec("⏸ 已暂停 —— 右键「录像」继续")
        else:
            self._set_rec("● 继续录像")

    # ---- 复制 / 收藏 / 历史 ----

    def set_starrable(self, db_path: str, ask_id: int) -> None:
        """刚答完的一轮落库了 —— 「收藏」亮起来，指到今天库里那条。"""
        self._starrable = (str(db_path), int(ask_id))
        self.star_btn.setText("收藏")
        self._sync_star()          # 能不能点由当前状态 + 有没有目标决定

    def set_star_label(self, starred: bool) -> None:
        """app 改完库回调：按钮文字跟真实状态走，金色「已收藏★」靠 starred 属性点亮。"""
        self.star_btn.setText("已收藏★" if starred else "收藏")
        self.star_btn.setProperty("starred", bool(starred))
        style = self.star_btn.style()
        style.unpolish(self.star_btn)        # 动态属性变了要重抛光，QSS 才会重算
        style.polish(self.star_btn)

    def _toggle_star(self) -> None:
        if self._starrable is None:
            return
        db_path, ask_id = self._starrable
        self.star_toggled.emit((db_path, ask_id))     # 改库归 app —— 改完回 set_star_label

    def _copy_answer(self) -> None:
        # 只复制答案，不带上面「我：」那一行
        text = (self._last_answer or self.answer.toPlainText()).strip()
        if not text:
            return
        QtWidgets.QApplication.clipboard().setText(text)
        self._set_status("已复制到剪贴板")
        QtCore.QTimer.singleShot(1600, self._restore_status_hint)

    def _restore_status_hint(self) -> None:
        if self._worker is not None or self._streaming:
            return
        if self._showing_history:
            self._set_status("这是历史记录 —— 要继续问，直接打字或先框一块屏")
        elif self._image_path and self._turns:
            self._set_status("还想追问就直接再打字（看的还是这张图）")
        elif self._image_path:
            self._set_status("想问这块屏的什么？（回车发送 · 答完还能接着追问）")
        elif self._turns:
            self._set_status("还想追问就直接再打字")
        elif self.answer.toPlainText().strip():
            self._set_status("这是历史记录 —— 要继续问，直接打字或先框一块屏")

    def _show_history(self) -> None:
        rows = self.history_provider() if self.history_provider else None
        menu = QtWidgets.QMenu(self)
        menu.addAction("最近的问答（[图]=带截图 · [文]=纯文字 · 点开可收藏）").setEnabled(False)
        menu.addSeparator()
        if not rows:
            menu.addAction("还没有问过").setEnabled(False)
        today_db = ""
        if self.history_db_path_provider is not None:
            try:
                today_db = self.history_db_path_provider() or ""
            except Exception:
                today_db = ""
        self._add_ask_rows(menu, rows or [], today_db)
        days = []
        if self.history_days_provider is not None:
            try:
                days = self.history_days_provider() or []
            except Exception:
                days = []                      # provider 坏了别拦着今天的菜单
        if days:
            menu.addSeparator()
            older = menu.addMenu("更早的日子 ▸")
            for label, db_path, day_rows in days:
                self._add_ask_rows(older.addMenu(label), day_rows, db_path)
        menu.exec(QtGui.QCursor.pos())

    def _add_ask_rows(self, menu, rows, db_path: str) -> None:
        """往菜单里铺一列问答行；点开 = 塞进答案区看全文（带着收藏信息）。"""
        for row in rows:
            ts, question, answer = row[0], row[1], row[2]
            question = question or ""
            kind = row[3] if len(row) > 3 else "text"
            image_path = row[4] if len(row) > 4 else ""
            ask_id = row[5] if len(row) > 5 else None
            stamp = str(ts)[11:16] if len(str(ts)) >= 16 else str(ts)
            short = question if len(question) <= 22 else question[:22] + "…"
            tag = "图" if kind == "image" else "文"
            action = menu.addAction(f"{stamp}  [{tag}]  {short}")
            tip = (answer or "")[:180]
            if image_path:
                tip = f"截图：{image_path}\n{tip}"
            action.setToolTip(tip)
            star_info = (db_path, ask_id) if (db_path and ask_id) else None
            action.triggered.connect(
                lambda checked=False, q=question, a=answer, k=kind, p=image_path, s=star_info:
                    self._show_past(q, a, k, p, s))

    def _show_past(self, question: str, answer: str, kind: str = "text",
                   image_path: str = "", star_info=None) -> None:
        """把一条历史问答塞进答案区看全文（不进当前对话上下文）。

        看完历史再打字 = **开一轮新对话**（上下文清掉）—— 界面已经被历史占满，
        再接着带旧 `_turns` 会让 AI 听到一串用户看不见的对话。
        """
        self._drop_running()
        self._turns = []                       # 看历史 ⇒ 后面那问不带旧上下文
        self._thread = uuid.uuid4().hex[:12]
        self._reset_answer()
        tag = "【图问】" if kind == "image" else "【文问】"
        head = f"{tag}{question}"
        if image_path:
            head += f"\n截图：{image_path}"
        body = answer or ""
        self._set_answer(f"{head}\n\n【答】{body}")
        self._last_answer = body               # 复制按钮只复制答案本身
        self._showing_history = True           # 这是历史记录，别把状态提示当成当前对话
        self._follow = False                   # 历史从头看 —— 别把视图拽到底
        self._starrable = star_info            # 带着库路径和 id ⇒ 这条能收藏
        self.star_btn.setText("收藏")
        self.set_state(STATE_HISTORY, status="这是历史记录 —— 要继续问，直接打字或先框一块屏")
        self.answer.verticalScrollBar().setValue(0)
        self.ask.setFocus()
