"""屏幕顶部的横栏：一条就够 —— 左侧框选 + 缩略图、中间输入、答案往下长。

不是独立小窗 —— 贴在屏幕上方、始终置顶、不用切窗口；**能拖着挪位置、能收成一条小条**。
**整个程序只有这一条**：启动就建好、空白时也在（顺便报「占了多少盘」），
框选 / 问答 / 占用都在这条上，不存在第二份界面。
"""
from __future__ import annotations

import json
import threading
import time
import uuid

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
QToolButton#tiny:disabled { color: #454a51; background: transparent; }
QLabel#status { color: #868c95; font-size: 12px; }
QLabel#rec { color: #ffb454; font-size: 11px; }
QLabel#usage { color: #6f757e; font-size: 11px; }
QLabel#thumb { border: 1px solid #3a3f46; border-radius: 8px; }
QTextBrowser#answer { background: #16181b; border: 1px solid #2c3036; border-radius: 10px;
                      color: #e2e5e9; padding: 12px 14px; font-size: 15px; }
"""

THUMB_W, THUMB_H = 64, 40
BUTTON_W = 68                # 底部那排按钮统一宽度 —— 文字在「置顶 / 不置顶」之间变也不挪位
MOVE_SLOP = 4                     # 拖动超过这么多像素才算「拖」，否则算「点」
_LINE_HEIGHT_PROPORTIONAL = 1     # QTextBlockFormat.ProportionalHeight（PySide6 里 int(枚举) 会报错）


def _ask_char() -> QtGui.QTextCharFormat:
    """「我」那句话：蓝底白字 —— **只包住文字**（不是整行一条）。

    用的是字符级背景，包多大取决于文字有多长；前后各塞一个空格当内边距。
    """
    fmt = QtGui.QTextCharFormat()
    fmt.setBackground(QtGui.QColor("#2d6cdf"))
    fmt.setForeground(QtGui.QColor("#ffffff"))
    return fmt


def _gap_block() -> QtGui.QTextBlockFormat:
    """空行（你的话和 AI 的回答之间隔开一点）。"""
    fmt = QtGui.QTextBlockFormat()
    fmt.setTopMargin(3)
    fmt.setBottomMargin(3)
    return fmt


def _answer_char() -> QtGui.QTextCharFormat:
    """AI 的回答：正常颜色（别继承了「我」那块的白字）。"""
    fmt = QtGui.QTextCharFormat()
    fmt.setForeground(QtGui.QColor("#e2e5e9"))
    return fmt


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


class _UsageWorker(QtCore.QThread):
    """占用数字在后台算 —— `usage.report()` 要整树 walk 盘，放主线程会卡界面。"""

    done = QtCore.Signal(object)     # Usage 实例，或 Exception

    def run(self):
        try:
            self.done.emit(usage.summary())
        except Exception as exc:                 # 后台线程里的异常别吞
            self.done.emit(exc)


class _AskWorker(QtCore.QThread):
    chunk = QtCore.Signal(str, bool)  # 流式：(新到的字, True = 整段替换/ False = 追加)
    done = QtCore.Signal(str)        # 完整答案（含已流出的部分）
    failed = QtCore.Signal(str)      # 失败原因（若已有部分文本，界面会留着）

    def __init__(self, image_path: str, question: str, history, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._question = question
        self._history = history
        self._cancelled = False
        self._abort = threading.Event()       # 传给 ask_stream：一置位就收摊
        self._sink: list = []                 # 底层响应，cancel 时 close 掐断连接

    def cancel(self) -> None:
        """这一轮不要了（用户开了新会话 / 清空）—— **连连接一起掐**，
        不然 HTTP 会一直挂到 90 秒超时才释放。
        """
        self._cancelled = True
        self._abort.set()
        for resp in self._sink:
            try:
                resp.close()
            except Exception:
                pass

    def run(self):
        parts: list[str] = []
        shown = ""                    # 已经显示出去的（清洗过之后的）累积文本
        try:
            for piece in backend.ask_stream(
                    self._image_path, self._question, self._history,
                    abort=self._abort, response_sink=self._sink):
                if self._cancelled:
                    return
                parts.append(piece)
                # 拿累积全文去洗：`**重点**` 常常被切成两片，洗单片是洗不掉的
                full = backend.tidy_so_far("".join(parts))
                if full == shown:
                    continue
                if shown and full.startswith(shown):
                    self.chunk.emit(full[len(shown):], False)   # 正常追加
                else:
                    self.chunk.emit(full, True)                 # 清洗改了已显示的部分 ⇒ 整段重放
                shown = full
            if self._cancelled:
                return
            text = backend.tidy_answer("".join(parts).strip())
            if not text:
                raise backend.AskError("答案回来了但是空的，再问一次试试。")
            self.done.emit(text)
        except backend.AskError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                      # 兜底：别让后台异常把界面搞死
            self.failed.emit(f"出错了：{exc}")


class AskBar(QtWidgets.QWidget):
    answered = QtCore.Signal(object)            # {question, answer, ms, kind, image_path, thread}
    exited = QtCore.Signal()                   # 用户把横栏收进托盘（✕）
    pick_requested = QtCore.Signal()           # 用户点了「框选」
    cleared = QtCore.Signal()                  # 用户点了「清空」—— app 去删临时截图

    def __init__(self, tip: str):
        super().__init__(None)
        self._tip = tip
        self._image_path = None
        self._worker = None
        self._timer = None
        self._dots = 0
        self._started_at = 0.0
        self._answer_cap = self._calc_answer_cap()   # 答案区高度上限（按屏幕比例，见 _calc_answer_cap）
        self._collapsed = False
        self._grab = None          # 拖动时：鼠标相对窗口左上角的偏移
        self._press = None
        self._moved = False
        self._turns: list[tuple[str, str]] = []   # 当前这轮的问答史（旧→新），追问时带给 AI
        self._thread = uuid.uuid4().hex[:12]      # 同一轮对话一个号，方便复盘
        self._workers: list[_AskWorker] = []      # 后台问答线程（退出时要 wait，见 shutdown）
        self._usage_worker = None                 # 后台算占用的那个线程
        self._streaming = False
        self._fit_timer = None        # 流式重排的节流器（别每片都排）
        self._answer_start = None     # 答案区里「答案」从第几个字符开始（None = 这一轮还没开始）
        self._turn_seq = 0            # 第几轮（被掐掉的旧那一轮回来时靠它认出来，别写回界面）
        self._last_answer = ""        # 最近一次的**答案**原文（复制按钮只复制它，不带问题）
        self._showing_history = False # 答案区现在显示的是历史记录（不是当前对话）
        self.history_provider = None              # app 塞进来的：() -> [(ts, question, answer, kind, image_path), ...]
        self._state = self._load_state()
        self._on_top = (config.ASK_BAR_ALWAYS_ON_TOP
                        if "always_on_top" not in self._state
                        else bool(self._state.get("always_on_top")))
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

    def _calc_answer_cap(self) -> int:
        """答案区高度上限 = 屏幕可用高度 × `ASK_BAR_ANSWER_MAX_RATIO`（再长就滚动）。"""
        area = self._usable()
        return max(200, int(area.height() * config.ASK_BAR_ANSWER_MAX_RATIO))

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
        # 用 Window（不是 Tool）才有任务栏按钮 —— 这样才能「固定到任务栏」。
        # ⚠️ 只在建窗时调一次：`setWindowFlags` 会把窗口藏掉再重建（闪一下），
        # 置顶与否后面一律走 `_topmost`（SetWindowPos 只动层级、窗口本身不动）。
        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window
        if self._on_top:
            flags |= QtCore.Qt.WindowStaysOnTopHint
        if int(self.windowFlags()) != int(flags):
            self.setWindowFlags(flags)

    def _topmost(self, on: bool) -> None:
        """置顶 / 取消置顶 —— **不改窗口标志**，直接跟 Windows 说。

        改用 `setWindowFlags` 会怎样：Qt 会先把窗口**藏掉再重建**，真机上就是闪一下，
        看着像冒出两个。用 `SetWindowPos` 只动层级，窗口本身不动。
        """
        try:
            import ctypes
            ctypes.windll.user32.SetWindowPos(
                int(self.winId()),
                -1 if on else -2,          # HWND_TOPMOST / HWND_NOTOPMOST
                0, 0, 0, 0,
                0x0001 | 0x0002 | 0x0010,  # 不改大小、不改位置、不抢焦点
            )
        except Exception:
            pass

    def toggle_always_on_top(self) -> None:
        """「置顶」开关：开着才挡别的界面；默认关。"""
        self._on_top = not self._on_top
        self._state["always_on_top"] = self._on_top
        self._topmost(self._on_top)     # 层级只走这一条 —— 别再 setWindowFlags（会闪）
        self._save_state()
        self.show_message("已开置顶 —— 横栏会一直在别的窗口上面。" if self._on_top
                          else "已关置顶 —— 别的窗口可以盖住横栏。")
        self._sync_top_btn()

    def show(self) -> None:
        # 不在这儿 `_apply_flags()`：那会 `setWindowFlags` 重建窗口（闪一下）。
        # 窗口标志建窗时已定，置顶与否由 `showEvent` 里的 `_topmost` 维持。
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
        self._set_copy_enabled(False)

        self.history_btn = QtWidgets.QToolButton(card)
        self.history_btn.setObjectName("tiny")
        self.history_btn.setText("历史")
        self.history_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.history_btn.setToolTip("看看今天问过什么")
        self.history_btn.clicked.connect(self._show_history)

        self.top_btn = QtWidgets.QToolButton(card)
        self.top_btn.setObjectName("tiny")
        self.top_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.top_btn.setToolTip("开着：横栏一直在别的窗口上面；关掉：别的窗口可以盖住它")
        self.top_btn.clicked.connect(self.toggle_always_on_top)
        self.top_btn.setCheckable(True)

        self.session_btn = QtWidgets.QToolButton(card)
        self.session_btn.setObjectName("tiny")
        self.session_btn.setText("新会话")
        self.session_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.session_btn.setToolTip("开一轮新对话：清掉上一题的上下文（图还在，不带上文）")
        self.session_btn.clicked.connect(self.new_session)

        self.clear_btn = QtWidgets.QToolButton(card)
        self.clear_btn.setObjectName("tiny")
        self.clear_btn.setText("清空")
        self.clear_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.clear_btn.setToolTip("对话完了清干净：答案、截图、上下文都不要了")
        self.clear_btn.clicked.connect(self.clear_session)

        # 按钮行：**位置必须恒定**。
        # 以前状态文字和按钮挤在同一行，状态一显示（「用了 0.8 秒…」）就把整排按钮往右推
        # 两百像素 ⇒ 用户按记忆中的位置点「新会话」，实际点到了「置顶」。
        # 现在：按钮各占固定宽度、整体靠右；状态文字单独一行放在下面（它会换行，但推不动按钮）。
        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addStretch(1)
        for btn in (self.top_btn, self.session_btn, self.clear_btn,
                    self.history_btn, self.copy_btn):
            btn.setFixedWidth(BUTTON_W)
            bottom.addWidget(btn)
        box.addLayout(bottom)
        self._sync_top_btn()

        box.addWidget(self.status)      # 单独一行：长短变化不影响上面那排按钮

        self.answer = QtWidgets.QTextBrowser(card)
        self.answer.setObjectName("answer")
        self.answer.setOpenExternalLinks(True)
        self.answer.setVisible(False)
        box.addWidget(self.answer)

        self.rec_line = QtWidgets.QLabel(card)      # 「● 记录中 …」—— 只在记录的时候露出来
        self.rec_line.setObjectName("rec")
        self.rec_line.setVisible(False)
        box.addWidget(self.rec_line)

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
        self._set_copy_enabled(bool(text.strip()))

    def _set_copy_enabled(self, on: bool) -> None:
        """「复制」**永远占着位置**，只切换能不能点。

        它一显隐，整排按钮就会跟着挪一格 ⇒ 用户按记忆中的位置点，就会点到旁边那个。
        """
        self.copy_btn.setEnabled(on)

    def _sync_top_btn(self) -> None:
        if not hasattr(self, "top_btn"):
            return
        self.top_btn.setText("置顶" if self._on_top else "不置顶")
        self.top_btn.setChecked(self._on_top)

    # ---- 状态切换 ----

    def set_idle(self) -> None:
        """回到「还没问东西」的样子。框选可选，不框也能直接打字问。"""
        self._turns = []
        self._thread = uuid.uuid4().hex[:12]
        self.drop_image()
        self._reset_answer()

    def _drop_running(self) -> None:
        """把正在写的那一轮掐掉 —— 用户要开新会话 / 清空时，别让他干等。

        ① **轮次号 +1**：旧那一轮的 chunk/done 回调拿的是旧号，一律不再往界面上写
        （否则「清空」后旧答案又冒出来，看着像没生效还多出一份）。
        ② 请求还在跑没关系：worker 被标了 cancel，结果不进界面；线程本体留给
        `shutdown()` 统一 wait，别在这儿丢引用。
        """
        self._turn_seq += 1
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.go.setEnabled(True)
        self._streaming = False

    def _reap_workers(self) -> None:
        """跑完的后台线程从清单里摘掉并销毁 —— 不摘会在 bar 底下越积越多。"""
        keep = []
        for w in self._workers:
            if w.isRunning():
                keep.append(w)
            else:
                w.deleteLater()
        self._workers = keep

    def shutdown(self) -> None:
        """退出前把后台线程收干净 —— QThread 还在跑就被销毁会崩（Destroyed while running）。"""
        self._drop_running()
        for worker in self._workers:
            worker.cancel()
            if not worker.wait(5000):          # 等它退出；等不到就硬停，别卡死退出
                worker.terminate()
                worker.wait(1000)
        self._workers.clear()
        if self._usage_worker is not None:
            if not self._usage_worker.wait(5000):
                self._usage_worker.terminate()
                self._usage_worker.wait(1000)
            self._usage_worker = None

    def new_session(self) -> None:
        """开新会话：清掉上一题上下文和答案，图留着接着问（不带上文）。

        上一句还在写也照样开 —— 那一轮直接不要了（原来只是提示一句就 return，
        结果旧答案写完又被写回界面，看着就像「点了没反应、还多出一份」）。
        """
        self._drop_running()
        self._turns = []
        self._thread = uuid.uuid4().hex[:12]
        self._reset_answer()
        if self._image_path:
            self.show_message("已开新会话 —— 不带上一题，看的还是这张图。")
        else:
            self.show_message("已开新会话 —— 直接打字问，或先框一块屏。")

    def clear_session(self) -> None:
        """清空：答案、截图、上下文都不要了（对话收尾）。还在写也照样清。"""
        self._drop_running()
        self.set_idle()
        self.cleared.emit()
        self.show_message("已清空 —— 直接打字问，或框一块屏再问。")

    def drop_image(self) -> None:
        """图不要了（收起 / 换一张）—— 纯文字照样能问，已有的答案文字留着。"""
        self._image_path = None
        self.thumb.setVisible(False)
        self.go.setEnabled(True)
        self.ask.setPlaceholderText(f"直接打字问就行；想问屏幕上的东西就先点「框选」或按 {self._tip}")

    def set_shot(self, image_path: str, shot: QtGui.QPixmap) -> None:
        """刚框好一块屏 —— 缩略图挂上，可以问了。换了图 ⇒ 旧对话史清掉、开新轮。"""
        self._drop_running()          # 旧那一轮（若有）别再往新图的界面上写
        self._image_path = image_path
        self._turns = []
        self._thread = uuid.uuid4().hex[:12]
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
        self._set_copy_enabled(False)
        self._streaming = False
        self._answer_start = None
        self._last_answer = ""
        self._showing_history = False

    def set_recording(self, on: bool, minutes: float = 0.0, switches: int = 0) -> None:
        """采集层开着的时候，横栏上给一行「● 记录中 …」—— 让人知道它在记。"""
        self.rec_line.setVisible(on)
        if on:
            self.rec_line.setText(f"● 记录中 {minutes:.0f} 分 · 切了 {switches} 次窗口")

    def refresh_usage(self) -> None:
        """占用数字在后台线程里算 —— walk 整个数据盘会卡界面，别放主线程。"""
        if self._usage_worker is not None and self._usage_worker.isRunning():
            return                             # 上一次还在算，别叠着起
        worker = _UsageWorker(self)
        worker.done.connect(self._apply_usage)
        self._usage_worker = worker
        worker.start()

    def _apply_usage(self, info) -> None:
        if isinstance(info, Exception):
            self.usage_line.setText(f"占用没算出来：{info}")
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
        self._topmost(self._on_top)      # 每次露出来都重申一遍层级（别的窗口可能盖过它）
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
        """✕：收进托盘 —— 程序不退。**只收界面**，图、答案、上下文都留着，叫回来接着用。

        原来这里顺手 `drop_image()` + 发 `exited` 让 app 删临时截图 —— 那是把
        「收起」当成了「清空」，正在问的那轮会被记成纯文字、截图也没了。
        删截图只归「清空 / 换一张 / 退出」管。
        """
        self._save_state()
        self.hide()
        self.exited.emit()

    # ---- 问 ----

    def _start_turn(self, question: str) -> None:
        """把问题先上屏 —— **蓝底白字、只包住文字的那一块是你的话**，下面空一行才是 AI 的回答。

        新一轮（还没写过 / 刚清空 / 刚开新会话）就先清掉旧的；
        追问就接在上一轮答案后面写，像聊天记录一样往下长。
        """
        if self._answer_start is None:
            self.answer.clear()
            self.answer.setFixedHeight(76)
            self._showing_history = False     # 新问起手，历史视图已经不在了
        cursor = self.answer.textCursor()
        if self.answer.toPlainText().strip():
            cursor.movePosition(QtGui.QTextCursor.End)
            cursor.insertBlock(_gap_block())      # 上一轮和这一轮之间空一行
        else:
            cursor.movePosition(QtGui.QTextCursor.Start)
        # 前后各一个空格 = 色块的内边距（Qt 富文本没有 padding，只能这样）
        cursor.insertText(f" {question} ", _ask_char())
        cursor.insertBlock(_gap_block(), _answer_char())   # 空一行
        cursor.insertBlock(_gap_block(), _answer_char())   # AI 的回答写在这一块
        self._answer_start = cursor.position()
        cursor.setCharFormat(_answer_char())     # 答案用正常颜色，别接着用蓝底那块的白字
        self.answer.setVisible(True)
        self.answer.setTextCursor(cursor)

    def submit(self) -> None:
        if self._worker is not None:
            # 别闷声不响地吞掉这一次回车 —— 不然用户只看到「按了没反应」
            self.show_message("上一句还在写 —— 等它写完，或者点「新会话」重开一轮。")
            return
        question = self.ask.text().strip()
        if not question:
            self.ask.setFocus()
            self.show_message("先打个问题（框不框选都行 —— 框了就问那块屏，不框就是纯文字问）。")
            return
        self.go.setEnabled(False)
        self._started_at = time.monotonic()
        self._dots = 0
        self._streaming = False
        self.status.setVisible(True)
        self.status.setText("在想…")
        self._set_copy_enabled(False)
        self._start_turn(question)
        self.ask.clear()              # 问题已经上屏了 ⇒ 输入框清空，直接打下一句
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(400)
        self._turn_seq += 1           # 开新的一轮：旧的（被掐掉的）回来时靠这个号认出来
        seq = self._turn_seq
        # 这一轮的图/文身份**当场拍死**：答案回来时界面可能已经换过图、甚至清过空，
        # 再读 self._image_path 会把图问答错记成纯文字、连归档截图都丢掉。
        kind = "image" if self._image_path else "text"
        image_path = self._image_path or ""
        self._worker = _AskWorker(self._image_path, question, list(self._turns), self)
        self._workers.append(self._worker)       # 留着，退出时要 wait（shutdown）
        self._worker.finished.connect(self._reap_workers)
        self._worker.chunk.connect(lambda piece, replace, s=seq: self._on_chunk(piece, replace, s))
        self._worker.done.connect(
            lambda text, s=seq, k=kind, p=image_path: self._finish(question, text, None, s, k, p))
        self._worker.failed.connect(
            lambda message, s=seq, k=kind, p=image_path: self._finish(question, "", message, s, k, p))
        self._worker.start()

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        label = "正在写" if self._streaming else "在想"   # 推理模型先想后写，前几秒没字是正常的
        self.status.setText(label + "·" * self._dots
                            + f"  {time.monotonic() - self._started_at:.0f} 秒")

    def _on_chunk(self, piece: str, replace: bool = False, seq: int = 0) -> None:
        """流式：字一到就往答案区追加（已经洗过 Markdown 噪声了）。

        问题那一行是 `_start_turn` 写好的，这里**只动答案那一段**，不能整段清掉。
        `seq` 是这一轮的号 —— 被掐掉的旧轮（清空/新会话/换图）流回来的碎片一律不进界面。
        """
        if seq != self._turn_seq:
            return
        if self.answer.isHidden():
            self.answer.setVisible(True)
        self._streaming = True
        self._set_copy_enabled(True)
        if replace:
            self._set_answer_part(piece)
        else:
            self.answer.moveCursor(QtGui.QTextCursor.End)
            self.answer.insertPlainText(piece)
            # 追加也要记进 _last_answer：复制按钮只认它，不认整篇文档（不然连「我：」那行一起拷）
            self._last_answer += piece
        self._schedule_fit()

    def _set_answer_part(self, text: str) -> None:
        """只替换「答案」那一段 —— 「我：」那一行留在上面不动。"""
        if self._answer_start is None:
            return
        cursor = self.answer.textCursor()
        cursor.setPosition(self._answer_start)
        cursor.movePosition(QtGui.QTextCursor.End, QtGui.QTextCursor.KeepAnchor)
        cursor.insertText(text, _answer_char())
        self._last_answer = text
        self._set_copy_enabled(bool(text.strip()))

    def _schedule_fit(self) -> None:
        """流式别每来一片就重排一遍答案区 —— 攒 80 毫秒再排，窗口不至于一路抖。"""
        if self._fit_timer is None:
            self._fit_timer = QtCore.QTimer(self)
            self._fit_timer.setSingleShot(True)
            self._fit_timer.timeout.connect(self._fit_answer)
        self._fit_timer.start(80)

    def _finish(self, question: str, text: str, error, seq: int = 0,
                kind: str = "text", image_path: str = "") -> None:
        # 被掐掉的旧那一轮（用户已经开了新会话 / 清空）跑完也会走到这儿 ——
        # 不挡住的话，旧答案会写在新界面上，看起来就像「新会话没生效、还多出一份」。
        # ⚠️ 别用 sender() 判断：信号是经 lambda 连的，PySide6 里拿不到发送者，
        # 判断会一直失败 ⇒ `_finish` 整个被跳过 ⇒ 计时器不停、按钮不恢复（真踩过）。
        # `kind` / `image_path` 是 submit 当场拍死的，不看现在的 self._image_path ——
        # 中途点 ✕ / 清空会把图丢掉，再读就会把图问答错记成纯文字。
        if seq != self._turn_seq:
            return
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._worker = None
        self._streaming = False
        self.go.setEnabled(True)
        ms = int((time.monotonic() - self._started_at) * 1000)
        self.answer.setVisible(True)
        if error:
            # 只看「答案那一段」有没有写出来的 —— 上面那行「我：」不算
            partial = self._last_answer.strip()
            if partial:
                # 流到一半断了：留着已写出的，底下标一句
                self.status.setText(f"回答中断 —— {error}")
                self._set_copy_enabled(True)
                # 已写出的那段也算上下文 —— 不然追问「继续」时 AI 记不得自己说过啥
                self._turns.append((question, partial))
            else:
                self._set_answer_part(error)
                self._set_copy_enabled(False)
                self.status.setText("没成功 —— 改一下再问")
        else:
            self._set_answer_part(text)
            self._set_copy_enabled(True)
            self._turns.append((question, text))
            if kind == "image":
                self.status.setText(
                    f"用了 {ms / 1000:.1f} 秒 · 还想追问就直接再打字（看的还是这张图）")
            else:
                self.status.setText(f"用了 {ms / 1000:.1f} 秒 · 还想追问就直接再打字")
            self.answered.emit({
                "question": question,
                "answer": text,
                "ms": ms,
                "kind": kind,
                "image_path": image_path,
                "thread": self._thread,
            })
        self._fit_answer()
        self.ask.setFocus(QtCore.Qt.OtherFocusReason)

    # ---- 复制 / 历史 ----

    def _copy_answer(self) -> None:
        # 只复制答案，不带上面「我：」那一行
        text = (self._last_answer or self.answer.toPlainText()).strip()
        if not text:
            return
        QtWidgets.QApplication.clipboard().setText(text)
        self.status.setVisible(True)
        self.status.setText("已复制到剪贴板")
        QtCore.QTimer.singleShot(1600, self._restore_status_hint)

    def _restore_status_hint(self) -> None:
        if self._worker is not None or self._streaming:
            return
        if self._showing_history:
            self.status.setText("这是历史记录 —— 要继续问，直接打字或先框一块屏")
        elif self._image_path and self._turns:
            self.status.setText("还想追问就直接再打字（看的还是这张图）")
        elif self._image_path:
            self.status.setText("想问这块屏的什么？（回车发送 · 答完还能接着追问）")
        elif self._turns:
            self.status.setText("还想追问就直接再打字")
        elif self.answer.toPlainText().strip():
            self.status.setText("这是历史记录 —— 要继续问，直接打字或先框一块屏")

    def _show_history(self) -> None:
        rows = self.history_provider() if self.history_provider else None
        menu = QtWidgets.QMenu(self)
        menu.addAction("今天的问答（[图]=带截图 · [文]=纯文字）").setEnabled(False)
        menu.addSeparator()
        if not rows:
            menu.addAction("今天还没问过").setEnabled(False)
        for row in rows or []:
            ts, question, answer = row[0], row[1], row[2]
            kind = row[3] if len(row) > 3 else "text"
            image_path = row[4] if len(row) > 4 else ""
            stamp = str(ts)[11:16] if len(str(ts)) >= 16 else str(ts)
            short = question if len(question) <= 22 else question[:22] + "…"
            tag = "图" if kind == "image" else "文"
            action = menu.addAction(f"{stamp}  [{tag}]  {short}")
            tip = (answer or "")[:180]
            if image_path:
                tip = f"截图：{image_path}\n{tip}"
            action.setToolTip(tip)
            action.triggered.connect(
                lambda checked=False, q=question, a=answer, k=kind, p=image_path:
                    self._show_past(q, a, k, p))
        menu.exec(QtGui.QCursor.pos())

    def _show_past(self, question: str, answer: str, kind: str = "text",
                   image_path: str = "") -> None:
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
        self._set_copy_enabled(bool(body.strip()))
        self.answer.setVisible(True)
        self.status.setText("这是历史记录 —— 要继续问，直接打字或先框一块屏")
        self._fit_answer()
        self.ask.setFocus()
