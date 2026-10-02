"""屏幕顶部的横栏：一条就够 —— 左侧框选 + 缩略图、中间输入、答案往下长。

不是独立小窗 —— 贴在屏幕上方、始终置顶、不用切窗口；**能拖着挪位置、能收成一条小条**。
**整个程序只有这一条**：启动就建好、空白时也在（顺便报「占了多少盘」），
框选 / 问答 / 占用都在这条上，不存在第二份界面。
"""
from __future__ import annotations

import json
import time

from PySide6 import QtCore, QtGui, QtWidgets

from learnsys import config
from learnsys.ask import backend, icon as icon_mod, usage

QSS = """
#bar { background: #1c1e22; border: 1px solid #34383f; border-radius: 14px; }
#pill { background: #1c1e22; border: 1px solid #34383f; border-radius: 16px; }
QLabel#handle { color: #6f757e; font-size: 15px; }
QLabel#pillTitle { color: #e6e9ec; font-size: 13px; font-weight: 600; }
QLabel#pillUsage { color: #868c95; font-size: 12px; }
QLabel#pillHint { color: #5aaaff; font-size: 12px; }
QPushButton#pick { background: #2b2f36; color: #d7dbe0; border: 1px solid #3a3f46;
                   border-radius: 10px; padding: 10px 16px; font-size: 14px; }
QPushButton#pick:hover { background: #363b44; border: 1px solid #5aaaff; color: #ffffff; }
QLineEdit#ask { background: #26292e; border: 1px solid #3a3f46; border-radius: 10px;
                color: #f1f3f4; padding: 10px 13px; font-size: 14px; }
QLineEdit#ask:focus { border: 1px solid #5aaaff; }
QPushButton#go { background: #2d6cdf; color: #ffffff; border: none; border-radius: 10px;
                 padding: 10px 22px; font-size: 14px; font-weight: 600; }
QPushButton#go:hover { background: #3b7bee; }
QPushButton#go:disabled { background: #33383f; color: #7e848c; }
QToolButton#tiny { color: #9aa0a6; background: transparent; border: none;
                   font-size: 15px; padding: 4px 9px; }
QToolButton#tiny:hover { color: #ffffff; background: #2c3037; border-radius: 8px; }
QLabel#status { color: #868c95; font-size: 12px; }
QLabel#usage { color: #6f757e; font-size: 11px; }
QLabel#thumb { border: 1px solid #3a3f46; border-radius: 8px; }
QTextBrowser#answer { background: #16181b; border: 1px solid #2c3036; border-radius: 10px;
                      color: #e2e5e9; padding: 12px 14px; font-size: 15px; }
"""

THUMB_W, THUMB_H = 64, 40
MOVE_SLOP = 4                     # 拖动超过这么多像素才算「拖」，否则算「点」
_LINE_HEIGHT_PROPORTIONAL = 1     # QTextBlockFormat.ProportionalHeight（PySide6 里 int(枚举) 会报错）


def _thumb(pixmap: QtGui.QPixmap, width: int, height: int) -> QtGui.QPixmap:
    """把截的那块缩成圆角小图（按原比例，居中留白，不裁内容）。"""
    box_w, box_h = width * 2, height * 2
    image = pixmap.toImage()
    image.setDevicePixelRatio(1.0)
    image = image.scaled(box_w, box_h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    image.setDevicePixelRatio(1.0)
    out = QtGui.QPixmap(box_w, box_h)
    out.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(out)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    path = QtGui.QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(box_w), float(box_h), 12.0, 12.0)
    painter.setClipPath(path)
    painter.drawImage((box_w - image.width()) // 2, (box_h - image.height()) // 2, image)
    painter.end()
    out.setDevicePixelRatio(2.0)
    return out


class _AskWorker(QtCore.QThread):
    chunk = QtCore.Signal(str)       # 流式：新到的一小段字
    done = QtCore.Signal(str)        # 完整答案（含已流出的部分）
    failed = QtCore.Signal(str)      # 失败原因（若已有部分文本，界面会留着）

    def __init__(self, image_path: str, question: str, history, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._question = question
        self._history = history

    def run(self):
        parts: list[str] = []
        try:
            for piece in backend.ask_stream(self._image_path, self._question, self._history):
                parts.append(piece)
                self.chunk.emit(piece)
            text = "".join(parts).strip()
            if not text:
                raise backend.AskError("答案回来了但是空的，再问一次试试。")
            self.done.emit(text)
        except backend.AskError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                      # 兜底：别让后台异常把界面搞死
            self.failed.emit(f"出错了：{exc}")


class AskBar(QtWidgets.QWidget):
    answered = QtCore.Signal(str, str, int)    # 问题, 答案, 毫秒
    exited = QtCore.Signal()                   # 用户把横栏收进托盘（✕）
    pick_requested = QtCore.Signal()           # 用户点了「框选」

    def __init__(self, tip: str):
        super().__init__(None)
        self._tip = tip
        self._image_path = None
        self._worker = None
        self._timer = None
        self._dots = 0
        self._started_at = 0.0
        self._answer_cap = 420
        self._collapsed = False
        self._grab = None          # 拖动时：鼠标相对窗口左上角的偏移
        self._press = None
        self._moved = False
        self._turns: list[tuple[str, str]] = []   # 当前这张图的问答史（旧→新），追问时带给 AI
        self._streaming = False
        self.history_provider = None              # app 塞进来的：() -> [(ts, question, answer), ...]
        self._state = self._load_state()
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("问一问 · 框选屏幕问 AI")
        self.setWindowIcon(icon_mod.icon())
        self._apply_flags()
        self._build()
        self._restore_place()
        self.set_idle()

    @property
    def busy(self) -> bool:
        return self._worker is not None

    # ---- 位置 / 收起状态（存在 D 盘的数据根目录里）----

    def _load_state(self) -> dict:
        try:
            data = json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self) -> None:
        state = dict(self._state)
        state["x"], state["y"] = self.x(), self.y()
        state["collapsed"] = self._collapsed
        self._state = state
        try:
            config.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            config.SETTINGS_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    def _usable(self) -> QtCore.QRect:
        area = QtCore.QRect()
        for screen in QtGui.QGuiApplication.screens():
            area = area.united(screen.availableGeometry())
        return area

    def _full_width(self) -> int:
        screen = QtGui.QGuiApplication.primaryScreen()
        wanted = int(screen.availableGeometry().width() * config.ASK_BAR_WIDTH_RATIO)
        return max(760, min(wanted, config.ASK_BAR_WIDTH_MAX))

    def _clamp(self) -> None:
        area = self._usable()
        x = max(area.left() - self.width() + 90, min(self.x(), area.right() - 90))
        y = max(area.top(), min(self.y(), area.bottom() - 40))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _place_default(self) -> None:
        area = self._usable()
        self.move(area.left() + (area.width() - self.width()) // 2,
                  area.top() + config.ASK_BAR_TOP_GAP)

    def _restore_place(self) -> None:
        self._collapsed = bool(self._state.get("collapsed"))
        self._apply_collapse()
        x, y = self._state.get("x"), self._state.get("y")
        area = self._usable()
        if isinstance(x, int) and isinstance(y, int) and area.contains(QtCore.QPoint(x, y)):
            self.move(x, y)
        else:
            self._place_default()

    def center_top(self) -> None:
        """回到屏幕正上方居中（托盘里那一条）。"""
        self._place_default()
        self._save_state()

    # ---- 置顶 / 任务栏 ----

    def _apply_flags(self) -> None:
        # 用 Window（不是 Tool）才有任务栏按钮 —— 这样才能「固定到任务栏」
        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window
        if config.ASK_BAR_ALWAYS_ON_TOP:
            flags |= QtCore.Qt.WindowStaysOnTopHint
        if int(self.windowFlags()) != int(flags):
            self.setWindowFlags(flags)

    def show(self) -> None:
        self._apply_flags()
        super().show()

    # ---- 界面 ----

    def _build(self) -> None:
        self.setStyleSheet(QSS)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 0)      # 上下给阴影留位置
        outer.setSpacing(0)

        self.card = QtWidgets.QFrame(self)
        self.card.setObjectName("bar")
        self.card.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        self.card.setToolTip(f"按住空白处可以把横栏拖到别处（{self._tip} 框选）")
        outer.addWidget(self.card)
        self._build_card(self.card)

        self.pill = QtWidgets.QFrame(self)
        self.pill.setObjectName("pill")
        self.pill.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        outer.addWidget(self.pill)
        self._build_pill(self.pill)
        self.pill.setVisible(False)

    def _build_card(self, card: QtWidgets.QFrame) -> None:
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 8)
        shadow.setColor(QtGui.QColor(0, 0, 0, 190))
        card.setGraphicsEffect(shadow)

        box = QtWidgets.QVBoxLayout(card)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(9)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)

        self.handle = QtWidgets.QLabel("⠿", card)
        self.handle.setObjectName("handle")
        row.addWidget(self.handle)

        self.pick_btn = QtWidgets.QPushButton("框选", card)
        self.pick_btn.setObjectName("pick")
        self.pick_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.pick_btn.setToolTip(f"框一块屏幕来问（{self._tip}）")
        self.pick_btn.clicked.connect(self.pick_requested.emit)
        row.addWidget(self.pick_btn)

        self.thumb = QtWidgets.QLabel(card)
        self.thumb.setObjectName("thumb")
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setToolTip("你框住的那块屏")
        self.thumb.setVisible(False)
        row.addWidget(self.thumb)

        self.ask = QtWidgets.QLineEdit(card)
        self.ask.setObjectName("ask")
        self.ask.returnPressed.connect(self.submit)
        row.addWidget(self.ask, 1)

        self.go = QtWidgets.QPushButton("问", card)
        self.go.setObjectName("go")
        self.go.setCursor(QtCore.Qt.PointingHandCursor)
        self.go.clicked.connect(self.submit)
        row.addWidget(self.go)

        self.collapse_btn = QtWidgets.QToolButton(card)
        self.collapse_btn.setObjectName("tiny")
        self.collapse_btn.setText("－")
        self.collapse_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.collapse_btn.setToolTip("收起成一条小条（点小条又能展开）")
        self.collapse_btn.clicked.connect(lambda: self.set_collapsed(True))
        row.addWidget(self.collapse_btn)

        close = QtWidgets.QToolButton(card)
        close.setObjectName("tiny")
        close.setText("✕")
        close.setCursor(QtCore.Qt.PointingHandCursor)
        close.setToolTip("收进托盘（程序不退出，随时能从托盘叫回来）")
        close.clicked.connect(self.hide_bar)
        row.addWidget(close)
        box.addLayout(row)

        self.status = QtWidgets.QLabel(card)
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setVisible(False)

        self.copy_btn = QtWidgets.QToolButton(card)
        self.copy_btn.setObjectName("tiny")
        self.copy_btn.setText("复制")
        self.copy_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.copy_btn.setToolTip("把答案全文复制到剪贴板")
        self.copy_btn.clicked.connect(self._copy_answer)
        self.copy_btn.setVisible(False)

        self.history_btn = QtWidgets.QToolButton(card)
        self.history_btn.setObjectName("tiny")
        self.history_btn.setText("历史")
        self.history_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.history_btn.setToolTip("看看今天问过什么")
        self.history_btn.clicked.connect(self._show_history)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.history_btn)
        bottom.addWidget(self.copy_btn)
        box.addLayout(bottom)

        self.answer = QtWidgets.QTextBrowser(card)
        self.answer.setObjectName("answer")
        self.answer.setOpenExternalLinks(True)
        self.answer.setVisible(False)
        box.addWidget(self.answer)

        self.usage_line = QtWidgets.QLabel(card)
        self.usage_line.setObjectName("usage")
        box.addWidget(self.usage_line)

    def _build_pill(self, pill: QtWidgets.QFrame) -> None:
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QtGui.QColor(0, 0, 0, 180))
        pill.setGraphicsEffect(shadow)

        lay = QtWidgets.QHBoxLayout(pill)
        lay.setContentsMargins(14, 7, 14, 7)
        lay.setSpacing(10)
        self.pill_title = QtWidgets.QLabel("问一问", pill)
        self.pill_title.setObjectName("pillTitle")
        self.pill_usage = QtWidgets.QLabel("", pill)
        self.pill_usage.setObjectName("pillUsage")
        self.pill_hint = QtWidgets.QLabel("展开 ▾", pill)
        self.pill_hint.setObjectName("pillHint")
        lay.addWidget(self.pill_title)
        lay.addWidget(self.pill_usage, 1)
        lay.addWidget(self.pill_hint)

    def _apply_collapse(self) -> None:
        if self._collapsed:
            self.card.setVisible(False)
            self.pill.setVisible(True)
            self.pill.setFixedWidth(config.ASK_BAR_PILL_WIDTH)
            self.setFixedWidth(config.ASK_BAR_PILL_WIDTH + 28)
        else:
            self.pill.setVisible(False)
            self.card.setVisible(True)
            self.setFixedWidth(self._full_width() + 28)
        self.adjustSize()

    def set_collapsed(self, flag: bool) -> None:
        if flag == self._collapsed:
            return
        self._collapsed = flag
        self._apply_collapse()
        self._clamp()
        self._fit_answer()
        if not flag:
            self.ask.setFocus(QtCore.Qt.OtherFocusReason)
        self._save_state()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def _place(self) -> None:                      # 兼容旧调用
        self._place_default()

    def _fit_answer(self) -> None:
        """答案区按内容长高（到上限就滚动），这样答案不用挤在小框里。"""
        if not self.answer.isVisible():
            return
        width = max(240, self.answer.viewport().width())
        document = self.answer.document()
        document.setTextWidth(width)
        needed = int(document.size().height()) + 24
        self.answer.setFixedHeight(max(76, min(needed, self._answer_cap)))
        self.adjustSize()

    def _set_answer(self, text: str) -> None:
        self.answer.setPlainText(text)
        fmt = QtGui.QTextBlockFormat()
        fmt.setLineHeight(165.0, _LINE_HEIGHT_PROPORTIONAL)
        cursor = self.answer.textCursor()
        cursor.select(QtGui.QTextCursor.Document)
        cursor.mergeBlockFormat(fmt)
        self.answer.moveCursor(QtGui.QTextCursor.Start)
        self.copy_btn.setVisible(bool(text.strip()))

    # ---- 状态切换 ----

    def set_idle(self) -> None:
        """回到「还没框东西」的样子。"""
        self._turns = []
        self.drop_image()
        self._reset_answer()

    def drop_image(self) -> None:
        """图不要了（收起 / 换一张）—— 剩下的答案文字留着。"""
        self._image_path = None
        self.thumb.setVisible(False)
        self.go.setEnabled(False)
        self.ask.setPlaceholderText(f"先点「框选」或按 {self._tip} 框一块屏幕，再打字问它")

    def set_shot(self, image_path: str, shot: QtGui.QPixmap) -> None:
        """刚框好一块屏 —— 缩略图挂上，可以问了。换了图 ⇒ 旧对话史清掉。"""
        self._image_path = image_path
        self._turns = []
        self.thumb.setPixmap(_thumb(shot, THUMB_W, THUMB_H))
        self.thumb.setVisible(True)
        self.go.setEnabled(True)
        self.ask.setPlaceholderText("想问这块屏的什么？（回车发送 · 答完还能接着追问）")
        self._reset_answer()
        if self._collapsed:
            self.set_collapsed(False)
        self.ask.setFocus(QtCore.Qt.OtherFocusReason)

    def _reset_answer(self) -> None:
        self.status.setVisible(False)
        self.status.clear()
        self.answer.setVisible(False)
        self.answer.clear()
        self.answer.setFixedHeight(76)
        self.copy_btn.setVisible(False)
        self._streaming = False

    def refresh_usage(self) -> None:
        """把「占了多少盘」更新到底部那一行 / 小条（鼠标悬停看明细）。"""
        try:
            info = usage.summary()
        except Exception as exc:
            self.usage_line.setText(f"占用没算出来：{exc}")
            self.pill_usage.setText("")
            return
        self.usage_line.setText(info.line)
        self.usage_line.setToolTip(info.detail)
        self.pill_usage.setText(info.short)
        self.pill.setToolTip(info.detail + chr(10) + "点一下展开 · 拖动可以挪位置")

    def show_message(self, text: str) -> None:
        self.status.setVisible(True)
        self.status.setText(text)

    # ---- 交互 ----

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_usage()
        self._clamp()
        self.raise_()
        if not self._collapsed:
            self.activateWindow()
            self.ask.setFocus(QtCore.Qt.OtherFocusReason)
        QtCore.QTimer.singleShot(0, self._fit_answer)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.hide_bar()
        else:
            super().keyPressEvent(event)

    # 拖动：空白处 / 缩略图 / 小条上按住就能挪；点一下小条 = 展开
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._grab = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press = event.globalPosition().toPoint()
            self._moved = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._grab is None:
            super().mouseMoveEvent(event)
            return
        point = event.globalPosition().toPoint()
        if (point - self._press).manhattanLength() > MOVE_SLOP:
            self._moved = True
        self.move(point - self._grab)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._grab is None:
            super().mouseReleaseEvent(event)
            return
        self._grab = None
        if self._moved:
            self._clamp()
            self._save_state()
        elif self._collapsed:
            self.set_collapsed(False)               # 收起时点一下 = 展开
        event.accept()

    def hide_bar(self) -> None:
        """✕：收进托盘 —— 程序不退。"""
        self.drop_image()
        self._save_state()
        self.hide()
        self.exited.emit()

    # ---- 问 ----

    def submit(self) -> None:
        if self._worker is not None:
            return
        if not self._image_path:
            self.show_message(f"还没框东西 —— 先点「框选」或按 {self._tip} 框一块屏幕。")
            return
        question = self.ask.text().strip()
        if not question:
            self.ask.setFocus()
            return
        self.go.setEnabled(False)
        self._started_at = time.monotonic()
        self._dots = 0
        self._streaming = False
        self.status.setVisible(True)
        self.status.setText("正在问…")
        self.copy_btn.setVisible(False)
        self.answer.setVisible(False)
        self.answer.clear()
        self.answer.setFixedHeight(76)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(400)
        self._worker = _AskWorker(self._image_path, question, list(self._turns), self)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(lambda text: self._finish(question, text, None))
        self._worker.failed.connect(lambda message: self._finish(question, "", message))
        self._worker.start()

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        label = "正在写" if self._streaming else "正在问"
        self.status.setText(label + "·" * self._dots
                            + f"  {time.monotonic() - self._started_at:.0f} 秒")

    def _on_chunk(self, piece: str) -> None:
        """流式：字一到就往答案区追加。"""
        if self.answer.isHidden():
            self.answer.setVisible(True)
            self.answer.clear()
            self._streaming = True
            self.copy_btn.setVisible(True)
        self.answer.moveCursor(QtGui.QTextCursor.End)
        self.answer.insertPlainText(piece)
        self._fit_answer()

    def _finish(self, question: str, text: str, error) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._worker = None
        self._streaming = False
        self.go.setEnabled(True)
        ms = int((time.monotonic() - self._started_at) * 1000)
        self.answer.setVisible(True)
        if error:
            partial = self.answer.toPlainText().strip()
            if partial:
                # 流到一半断了：留着已写出的，底下标一句
                self.status.setText(f"回答中断 —— {error}")
                self.copy_btn.setVisible(True)
            else:
                self._set_answer(error)
                self.copy_btn.setVisible(False)
                self.status.setText("没成功 —— 改一下再问")
        else:
            self._set_answer(text)
            self.copy_btn.setVisible(True)
            self._turns.append((question, text))
            if self._image_path:
                self.status.setText(
                    f"用了 {ms / 1000:.1f} 秒 · 还想追问就直接再打字（看的还是这张图）")
            else:
                self.status.setText(f"用了 {ms / 1000:.1f} 秒")
            self.answered.emit(question, text, ms)
        self._fit_answer()
        self.ask.selectAll()

    # ---- 复制 / 历史 ----

    def _copy_answer(self) -> None:
        text = self.answer.toPlainText().strip()
        if not text:
            return
        QtWidgets.QApplication.clipboard().setText(text)
        self.status.setVisible(True)
        self.status.setText("已复制到剪贴板")
        QtCore.QTimer.singleShot(1600, self._restore_status_hint)

    def _restore_status_hint(self) -> None:
        if self._worker is not None or self._streaming:
            return
        if self._image_path and self._turns:
            self.status.setText("还想追问就直接再打字（看的还是这张图）")
        elif self._image_path:
            self.status.setText("想问这块屏的什么？（回车发送 · 答完还能接着追问）")
        elif self.answer.toPlainText().strip():
            self.status.setText("这是历史记录 —— 要继续问，先框一块屏")

    def _show_history(self) -> None:
        rows = self.history_provider() if self.history_provider else None
        menu = QtWidgets.QMenu(self)
        menu.addAction("今天的问答").setEnabled(False)
        menu.addSeparator()
        if not rows:
            menu.addAction("今天还没问过").setEnabled(False)
        for ts, question, answer in rows or []:
            stamp = str(ts)[11:16] if len(str(ts)) >= 16 else str(ts)
            short = question if len(question) <= 22 else question[:22] + "…"
            action = menu.addAction(f"{stamp}  {short}")
            action.setToolTip((answer or "")[:180])
            action.triggered.connect(
                lambda checked=False, q=question, a=answer: self._show_past(q, a))
        menu.exec(QtGui.QCursor.pos())

    def _show_past(self, question: str, answer: str) -> None:
        """把一条历史问答塞进答案区看全文（不进当前对话上下文）。"""
        self._reset_answer()
        self._set_answer(f"【问】{question}\n\n【答】{answer}")
        self.answer.setVisible(True)
        self.copy_btn.setVisible(True)
        self.status.setText("这是历史记录 —— 要继续问，先框一块屏")
        self._fit_answer()
        self.ask.setFocus()
