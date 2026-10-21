"""屏幕顶部的横栏：一条就够 —— 左侧框选 + 缩略图、中间输入、答案往下长。

不是独立小窗 —— 贴在屏幕上方、始终置顶、不用切窗口；**能拖着挪位置、能收成一条小条**。
**整个程序只有这一条**：启动就建好、空白时也在（顺便报「占了多少盘」），
框选 / 问答 / 占用都在这条上，不存在第二份界面。
"""
from __future__ import annotations

import json
import pathlib
import re
import threading
import time
import uuid

from PySide6 import QtCore, QtGui, QtWidgets

from learnsys import agent, config
from learnsys.ask import icon as icon_mod, usage

# 设计规范（改样式先看这里，别一处一处试）：
#   底色  卡片 #1b1e23 ｜ 输入 #23262b ｜ 答案区 #15171a（一层比一层深，视线自然往下走）
#   强调  蓝 #4d8bff（问 / 复盘 / 输入焦点 / 菜单选中）
#   语义  清空=危险（悬停泛红）｜ 收藏=金色（已收藏★）｜ 置顶开=蓝字
#   圆角  卡片 14 ｜ 输入/按钮/答案 10 ｜ 小按钮 8 ｜ 菜单 10
#   字号  答案 15 ｜ 输入/主按钮 14 ｜ 小按钮 13 ｜ 状态 12 ｜ 占用/记录 11
#   ⚠️ 按钮宽度 BUTTON_W 恒定、位置不动 —— 美化不许破坏肌肉记忆（见按钮行注释）
QSS = """
QFrame#bar { background: #1b1e23; border: 1px solid #33383f; border-radius: 14px;
             font-family: "Microsoft YaHei UI"; }
QFrame#pill { background: #1b1e23; border: 1px solid #33383f; border-radius: 16px;
              font-family: "Microsoft YaHei UI"; }
QLabel#handle { color: #6f757e; font-size: 15px; }
QLabel#pillTitle { color: #e6e9ec; font-size: 13px; font-weight: 600; }
QLabel#pillUsage { color: #868c95; font-size: 12px; }
QLabel#pillHint { color: #5aaaff; font-size: 12px; }

QPushButton#pick { background: #262b31; color: #d7dbe0; border: 1px solid #3a3f46;
                   border-radius: 10px; padding: 9px 16px; font-size: 14px; }
QPushButton#pick:hover { background: #303743; border-color: #4d8bff; color: #ffffff; }
QPushButton#pick:pressed { background: #242a31; }

QLineEdit#ask { background: #23262b; border: 1px solid #3a3f46; border-radius: 10px;
                color: #f1f3f4; padding: 9px 13px; font-size: 14px;
                selection-background-color: #2f6bed; }
QLineEdit#ask:focus { border: 1px solid #4d8bff; background: #25282d; }

QPushButton#go { background: #2f6bed; color: #ffffff; border: none; border-radius: 10px;
                 padding: 9px 24px; font-size: 14px; font-weight: 600; }
QPushButton#go:hover { background: #3d78f2; }
QPushButton#go:pressed { background: #2a5fd0; }
QPushButton#go:disabled { background: #33383f; color: #7e848c; }

QToolButton#tiny { color: #9aa0a6; background: transparent; border: 1px solid transparent;
                   font-size: 13px; padding: 5px 8px; border-radius: 8px; }
QToolButton#tiny:hover { color: #ffffff; background: #2c3037; }
QToolButton#tiny:pressed { background: #262a30; }
QToolButton#tiny:disabled { color: #474c53; background: transparent; }
QToolButton#tiny:checked { color: #5aaaff; }          /* 置顶开着时亮蓝 */
QToolButton[role="accent"] { color: #6ea8ff; }         /* 复盘：主操作，蓝字 */
QToolButton[role="accent"]:hover { color: #a8ccff; background: #243043; }
QToolButton[role="danger"]:hover { color: #ff8177; background: #34262a; }  /* 清空：悬停泛红 */
QToolButton[role="recording"] { color: #ff8177; }      /* 录制中：红字提醒 */
QToolButton[starred="true"] { color: #f5b74e; }        /* 已收藏：金字 */

QLabel#status { color: #98a1ab; font-size: 12px; }
QLabel#rec { color: #ffb454; font-size: 11px; }
QLabel#usage { color: #6f757e; font-size: 11px; }
QLabel#thumb { border: 1px solid #3a3f46; border-radius: 8px; }

QTextBrowser#answer { background: #171c23; border: 1px solid #283039; border-radius: 10px;
                      color: #dfe6ee; padding: 13px 16px; font-size: 15px;
                      selection-background-color: #35618f; }

QFrame#grip { background: #2a2f36; border-radius: 3px; }
QFrame#grip:hover { background: #4d8bff; }           /* 拖底边改答案区高度 */

QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 2px 4px 0; }
QScrollBar::handle:vertical { background: #3a4048; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4a525c; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QMenu { background: #202329; border: 1px solid #33383f; border-radius: 10px; padding: 6px; }
QMenu::item { color: #d7dbe0; background: transparent; padding: 7px 24px 7px 14px;
              border-radius: 6px; font-size: 13px; }
QMenu::item:selected { background: #2f6bed; color: #ffffff; }
QMenu::item:disabled { color: #6b7178; }
QMenu::separator { height: 1px; background: #33383f; margin: 5px 8px; }

QToolTip { background: #202329; color: #d7dbe0; border: 1px solid #33383f;
           padding: 4px 6px; font-size: 12px; }
"""

THUMB_W, THUMB_H = 64, 40
BUTTON_W = 68                # 底部那排按钮统一宽度 —— 文字在「置顶 / 不置顶」之间变也不挪位

# ---- 固定几何（T3.5）----
# 每一行都钉死高度，窗口尺寸只由这些常量 + 答案面板高度算出来。
# 内容怎么长、状态文字多长，都不许再把窗口撑大或推按钮。
BAR_OUTER_X = 14             # 窗口左右留白（给阴影）
BAR_OUTER_TOP = 12           # 窗口顶部留白（给阴影）
CARD_PAD_X = 12
CARD_PAD_TOP = 10
CARD_PAD_BOTTOM = 10
CARD_GAP = 9                 # 卡片内各行间距
ROW_H = 40                   # 输入行（缩略图 40 高，整行跟着它）
BUTTON_H = 28                # 底部按钮行
STATUS_H = 22                # 状态行 —— 永远占着，长短只截断不换行
REC_H = 18                   # 录制信息行 —— 永远占着
USAGE_H = 16                 # 占用行
GRIP_H = 7                   # 答案面板底边的拖拽条
PILL_H = 44                  # 收起后的小条

# 状态机：所有界面显隐只认这一组名字（见 set_state）
STATE_IDLE = "idle"
STATE_THINKING = "thinking"
STATE_STREAMING = "streaming"
STATE_DONE = "done"
STATE_ERROR = "error"
STATE_HISTORY = "history"
_ANSWER_STATES = frozenset({STATE_THINKING, STATE_STREAMING, STATE_DONE,
                            STATE_ERROR, STATE_HISTORY})
_STATES = frozenset({STATE_IDLE, *_ANSWER_STATES})

MODE_LABELS = {
    "explain": "讲解（完整回答 + 思考题）",
    "guide": "引导（先给提示，再反问）",
    "quiz": "测验（出题 + 逐题批改）",
    "quick": "速答（短）",
}
MOVE_SLOP = 4                     # 拖动超过这么多像素才算「拖」，否则算「点」
_LINE_HEIGHT_PROPORTIONAL = 1     # QTextBlockFormat.ProportionalHeight（PySide6 里 int(枚举) 会报错）
_USAGE_TTL_SECONDS = 300.0        # 占用数字缓存多久：横栏每次露出来都触发，不缓存就是每次全盘 walk
_SCROLL_SLACK = 8                 # 滚动条离底部不足这么多像素 = 「正跟着看最新」


def _as_bool(value, default: bool) -> bool:
    """把设置文件里的值当开关读 —— `"false"` / `"0"` / `"关"` 是 False，不是 `bool(str)` 的 True。"""
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off", "关", "否")


def _ask_char() -> QtGui.QTextCharFormat:
    """「我」那句话：雾蓝底、近白的字 —— 只包住文字（不是整行一条）。

    用的是字符级背景，包多大取决于文字有多长；前后各塞一个空格当内边距。
    颜色特意比按钮的强调蓝灰一档：控件要醒目，对话要柔和（「自然清新」的出处）。
    """
    fmt = QtGui.QTextCharFormat()
    fmt.setBackground(QtGui.QColor("#35618f"))
    fmt.setForeground(QtGui.QColor("#f0f5fc"))
    return fmt


def _gap_block() -> QtGui.QTextBlockFormat:
    """空行（你的话和 AI 的回答之间隔开一点），顺带定 165% 行高 —— 对话区排版统一。

    上下留白 4px：对话内容要「呼吸感」，宁可窗口高一点也别挤成一团。
    """
    fmt = QtGui.QTextBlockFormat()
    fmt.setTopMargin(4)
    fmt.setBottomMargin(4)
    fmt.setLineHeight(165.0, _LINE_HEIGHT_PROPORTIONAL)
    return fmt


def _answer_char() -> QtGui.QTextCharFormat:
    """AI 的回答：柔和的冷白（别继承「我」那块的字色，也别纯白刺眼）。"""
    fmt = QtGui.QTextCharFormat()
    fmt.setForeground(QtGui.QColor("#dce4ee"))
    return fmt


def _markdown_bold_for_qt(text: str) -> str:
    """把 `**加粗**` 换成 Qt 认的行内 `<b>`，但跳过 ``` 代码围栏。

    Qt 的 Markdown 解析器对「**（中文括号）**」这种边界会漏解析，
    把 `**` 原样留在界面上；换行内 HTML 能稳定加粗。代码围栏里的
    `a ** b` / `**kwargs` 不能动，所以按围栏切开只处理正文段。
    """
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"\*\*([^*\n]+?)\*\*", r"<b>\1</b>", parts[i])
    return "".join(parts)


def _thumb(pixmap: QtGui.QPixmap, width: int, height: int) -> QtGui.QPixmap:
    """把截的那块缩成圆角小图（按原比例，居中留白，不裁内容）。"""
    if pixmap is None or pixmap.isNull():
        return QtGui.QPixmap(width, height)          # 空图给空白，别炸在 toImage()
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
    activity = QtCore.Signal(str)    # 状态行的一句话：看图 / 查记录 / 推理中

    def __init__(self, image_path: str, question: str, history, parent=None, context: str = "",
                 extra_images: list[str] | None = None, mode: str = "explain"):
        super().__init__(parent)
        self._image_path = image_path
        self._question = question
        self._history = history
        self._context = context      # 课上转写片段（追问时捎给 AI，界面不显示）
        self._extra_images = list(extra_images or [])  # 复盘附带的屏幕快照
        self._mode = mode
        self._system_override = ""     # 电脑助手等非导师任务用
        self._use_tools = True
        self._conversation_key = ""    # 同一轮对话的稳定号，测验收错题去重用
        self._cancelled = False
        self._abort = threading.Event()       # 传给 Agent：一置位就收摊
        self._sink: list = []                 # 底层响应，cancel 时 close 掐断连接
        self._last_activity = ""              # 同一句话只发一次（思考增量每片都来，别刷屏）

    def _say(self, text: str) -> None:
        text = str(text or "")
        if text and text != self._last_activity:
            self._last_activity = text
            self.activity.emit(text)

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
        final = ""
        try:
            request = agent.AgentRequest(
                message=self._question,
                history=self._history,
                image_path=self._image_path,
                extra_images=self._extra_images,
                context=self._context,
                mode=self._mode,
                system_override=self._system_override,
                use_tools=self._use_tools,
                conversation_key=self._conversation_key,
            )
            for event in agent.run(request, abort=self._abort, response_sink=self._sink):
                if self._cancelled:
                    return
                if event.kind == "text":
                    parts.append(event.text)
                    self.chunk.emit(event.text, False)
                elif event.kind == "thinking":
                    self._say("正在推理…")
                elif event.kind == "vision":
                    if event.text:
                        self._say(event.text)
                    elif event.data:
                        used = event.data.get("used_vision")
                        self._say("看图完成（视觉模型）" if used
                                  else "看图完成（只读了文字，没看到图）")
                elif event.kind == "tool_start":
                    name = event.data.get("name") or "记录"
                    self._say(f"查找：{name}…")
                elif event.kind == "tool_end":
                    self._say(str(event.data.get("preview") or "整理答案…"))
                elif event.kind == "error":
                    self.failed.emit(event.text)
                    return
                elif event.kind == "done":
                    final = str(event.data.get("text") or "")
            if self._cancelled:
                return
            text = (final or "".join(parts)).strip()
            if not text:
                raise agent.AgentError("答案回来了但是空的，再问一次试试。")
            self.done.emit(text)
        except agent.AgentError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                      # 兜底：别让后台异常把界面搞死
            self.failed.emit(f"出错了：{exc}")


class _AnswerGrip(QtWidgets.QFrame):
    """答案面板底边的拖拽条：往下拖加高、往上拖缩矮。

    只发「相对按下时挪了多少」—— 由 AskBar 统一夹到上下限并重算窗口几何，
    面板自己有固定高度，内容再多也只滚动、不长高。
    """

    moved = QtCore.Signal(int)
    released = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("grip")
        self.setFixedHeight(GRIP_H)
        self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
        self.setToolTip("按住往下拖：答案区变高；往上拖：变矮")
        self._start = None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._start = int(event.globalPosition().y())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start is None:
            super().mouseMoveEvent(event)
            return
        self.moved.emit(int(event.globalPosition().y()) - self._start)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._start is None:
            super().mouseReleaseEvent(event)
            return
        self._start = None
        self.released.emit()
        event.accept()


class AskBar(QtWidgets.QWidget):
    answered = QtCore.Signal(object)            # {question, answer, ms, kind, image_path, thread}
    exited = QtCore.Signal()                   # 用户把横栏收进托盘（✕）
    pick_requested = QtCore.Signal()           # 用户点了「框选」
    cleared = QtCore.Signal()                  # 用户点了「清空」—— app 去删临时截图
    review_requested = QtCore.Signal()         # 用户点了「复盘」—— app 拿今天的记录去问 AI
    star_toggled = QtCore.Signal(object)       # 用户点了「收藏」—— (db_path, ask_id)，app 改库
    record_toggled = QtCore.Signal()           # 用户点了「录制」—— app 开/停三路录制
    quiz_requested = QtCore.Signal()           # 用户点了「测验」—— app 出 5 道题
    rec_pause_toggled = QtCore.Signal()        # 右键录制按钮 → 暂停/继续
    rec_timer_set = QtCore.Signal(int)         # 右键录制按钮 → 定时停止（分钟，0=取消）
    report_requested = QtCore.Signal()         # 「⋯」菜单 → 生成学习报告
    notes_requested = QtCore.Signal()          # 「⋯」菜单 → 导出对话笔记
    anki_requested = QtCore.Signal()           # 「⋯」菜单 → 导出错题本
    computer_request = QtCore.Signal(str)      # 输入 > 开头 = 电脑助手（AI 出操作计划）
    ops_result = QtCore.Signal(str)            # 电脑助手每步执行结果（后台线程发）
    remind_scheduled = QtCore.Signal(int, str)  # 计划里出现 remind → app 挂定时器
    workbench_requested = QtCore.Signal()      # 「工作台」→ app 打开独立学习台窗口

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
        self._activity = ""           # 状态行的一句话（看图 / 查记录 / 推理中）
        self.ask_mode = "explain"     # 讲解 / 引导 / 测验 / 速答（Web 工作台可改）
        self.quiz_mode = False        # 托盘点「测验」后粘住，直到新会话/清空/换模式
        self._answer_start = None     # 答案区里「答案」从第几个字符开始（None = 这一轮还没开始）
        self._turn_seq = 0            # 第几轮（被掐掉的旧那一轮回来时靠它认出来，别写回界面）
        self._last_answer = ""        # 最近一次的**答案**原文（复制按钮只复制它，不带问题）
        self._showing_history = False # 答案区现在显示的是历史记录（不是当前对话）
        self._follow = True           # 流式时视图跟着最新内容走；用户往上翻了就停（见 _on_chunk）
        self._usage_cache = None      # 最近一次算好的占用（Usage）—— 5 分钟内直接用，别反复 walk 盘
        self._usage_at = 0.0
        self._starrable = None        # 当前内容能收藏的那条问答：(db_path, ask_id)；None = 没得收藏
        self.doc_path: str | None = None   # 挂载的课件文档（提问时正文一起带上）
        self.doc_name = ""
        self.doc_text = ""
        self.ops_result.connect(self.append_text)
        self.extra_context_provider = None   # app 塞的：() -> str，追问时附带的课上转写片段
        self.history_provider = None         # app 塞的：() -> [(ts, question, answer, kind, image_path, id), ...]
        self.history_days_provider = None    # app 塞的：() -> [(label, db_path, rows), ...] 更早的日子
        self.history_db_path_provider = None  # app 塞的：() -> str，今天那个库的路径（收藏要落对库）
        self._state = self._load_state()
        self._answer_shown = False    # 答案面板是否在版面上（只有 set_state 能改）
        self._answer_h = self._load_answer_h()
        self._status_text = ""        # 状态行全文（界面上是截断版，悬停看全文）
        self._recording = False
        self._rec_text = ""           # 录制行全文（界面上可能被截断）
        self._drag_base = None        # 拖答案底边时的起始高度
        self._state_name = STATE_IDLE
        # 界面设置里的 always_on_top 可能被手改成字符串 "false" —— `bool("false")` 是 True！
        # 走和 `config._user_bool` 同一套判法，别自己 bool()。
        self._on_top = _as_bool(self._state.get("always_on_top", config.ASK_BAR_ALWAYS_ON_TOP),
                                config.ASK_BAR_ALWAYS_ON_TOP)
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

    def _load_answer_h(self) -> int:
        """答案面板高度：上次拖到多少就恢复多少，夹在 [最矮, 屏高上限] 之间。"""
        try:
            value = int(self._state.get("answer_h", config.ASK_BAR_ANSWER_DEFAULT_H))
        except (TypeError, ValueError):
            value = config.ASK_BAR_ANSWER_DEFAULT_H
        return max(config.ASK_BAR_ANSWER_MIN_H, min(value, self._answer_cap))

    def _save_state(self) -> None:
        state = dict(self._state)
        state["x"], state["y"] = self.x(), self.y()
        state["collapsed"] = self._collapsed
        state["answer_h"] = self._answer_h
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
        self._apply_geometry()
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
        """置顶 / 取消置顶。

        原本只调 SetWindowPos(HWND_TOPMOST/NOTOPMOST)，想免掉 setWindowFlags 的闪动 ——
        真机实测这条路在 Qt 6.11 上**不可靠**：窗口标志里带着 WindowStaysOnTopHint 时，
        Qt 按缓存的标志反复把 WS_EX_TOPMOST 顶回去，SetWindowPos 降了也白降
        （真踩过：点「不置顶」横栏照样盖着一切）。所以改成：
        ① 先试无闪动的 SetWindowPos（参数补齐 argtypes）；
        ② 用 GetWindowLongW 验证实际状态，达标就收工；
        ③ 不达标老实走 setWindowFlags 重建窗口（闪一下 —— 罕见操作，对 > 快）。
        """
        try:
            import ctypes
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            hwnd = wt.HWND(int(self.winId()))
            user32.SetWindowPos(hwnd, wt.HWND(-1 if on else -2), 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0010)   # 不改大小/位置、不抢焦点
            style = user32.GetWindowLongW(hwnd, -20)         # GWL_EXSTYLE
            if bool(style & 0x8) == on:                      # WS_EX_TOPMOST 与目标一致 ⇒ 成功
                return
        except Exception:
            pass
        # 兜底：改 Qt 窗口标志（窗口会重建、闪一下），位置先记下来再还原
        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window
        if on:
            flags |= QtCore.Qt.WindowStaysOnTopHint
        if int(self.windowFlags()) != int(flags):
            pos = self.pos()
            self.setWindowFlags(flags)
            self.show()
            self.move(pos)

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
        outer.setContentsMargins(BAR_OUTER_X, BAR_OUTER_TOP, BAR_OUTER_X, 0)  # 给阴影留位置
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
        box.setContentsMargins(CARD_PAD_X, CARD_PAD_TOP, CARD_PAD_X, CARD_PAD_BOTTOM)
        box.setSpacing(CARD_GAP)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)

        self.handle = QtWidgets.QLabel("⠿", card)
        self.handle.setObjectName("handle")
        row.addWidget(self.handle)

        self.pick_btn = QtWidgets.QPushButton("框选", card)
        self.pick_btn.setObjectName("pick")
        self.pick_btn.setFixedHeight(ROW_H - 2)
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
        self.ask.setFixedHeight(ROW_H - 2)
        self.ask.returnPressed.connect(self.submit)
        row.addWidget(self.ask, 1)

        self.go = QtWidgets.QPushButton("问", card)
        self.go.setObjectName("go")
        self.go.setFixedHeight(ROW_H - 2)
        self.go.setCursor(QtCore.Qt.PointingHandCursor)
        self.go.clicked.connect(self.submit)
        row.addWidget(self.go)

        self.collapse_btn = QtWidgets.QToolButton(card)
        self.collapse_btn.setObjectName("tiny")
        self.collapse_btn.setText("－")
        self.collapse_btn.setFixedHeight(ROW_H - 2)
        self.collapse_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.collapse_btn.setToolTip("收起成一条小条（点小条又能展开）")
        self.collapse_btn.clicked.connect(lambda: self.set_collapsed(True))
        row.addWidget(self.collapse_btn)

        close = QtWidgets.QToolButton(card)
        close.setObjectName("tiny")
        close.setText("✕")
        close.setFixedHeight(ROW_H - 2)
        close.setCursor(QtCore.Qt.PointingHandCursor)
        close.setToolTip("收进托盘（程序不退出，随时能从托盘叫回来）")
        close.clicked.connect(self.hide_bar)
        row.addWidget(close)
        box.addLayout(row)

        # 状态行：固定高度、不换行 —— 长了只截断（悬停看全文），绝不推窗口/按钮
        self.status = QtWidgets.QLabel(card)
        self.status.setObjectName("status")
        self.status.setWordWrap(False)
        self.status.setFixedHeight(STATUS_H)

        # 录制信息行：固定高度、常驻版面（不录制时是空行）—— 显隐不再改变窗口高度
        self.rec_line = QtWidgets.QLabel(card)
        self.rec_line.setObjectName("rec")
        self.rec_line.setWordWrap(False)
        self.rec_line.setFixedHeight(REC_H)
        self.rec_line.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        # 状态和录制并成一行（左状态、右录制）—— 布局在按钮行之后再加
        self.info_row = QtWidgets.QHBoxLayout()
        self.info_row.setSpacing(12)
        self.info_row.addWidget(self.status, 1)
        self.info_row.addWidget(self.rec_line, 0)

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
        self.clear_btn.setProperty("role", "danger")   # 清空是危险动作：悬停泛红（见 QSS）
        self.clear_btn.setText("清空")
        self.clear_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.clear_btn.setToolTip("对话完了清干净：答案、截图、上下文都不要了")
        self.clear_btn.clicked.connect(self.clear_session)

        self.star_btn = QtWidgets.QToolButton(card)
        self.star_btn.setObjectName("tiny")
        self.star_btn.setText("收藏")
        self.star_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.star_btn.setToolTip("把这条问答收进错题本 —— 托盘里能一键导出成 Anki 的 CSV")
        self.star_btn.clicked.connect(self._toggle_star)
        self.star_btn.setEnabled(False)      # 有「当前这条」（历史/刚答完）才亮

        self.review_btn = QtWidgets.QToolButton(card)
        self.review_btn.setObjectName("tiny")
        self.review_btn.setProperty("role", "accent")  # 复盘是主操作：常亮蓝字（见 QSS）
        self.review_btn.setText("复盘")
        self.review_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.review_btn.setToolTip("拿今天记录的窗口和课堂转写问 AI：我刚才学了什么？（要先在托盘「开始记录」）")
        self.review_btn.clicked.connect(self.review_requested.emit)

        self.workbench_btn = QtWidgets.QToolButton(card)
        self.workbench_btn.setObjectName("tiny")
        self.workbench_btn.setText("工作台")
        self.workbench_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.workbench_btn.setToolTip("在独立窗口里打开学习台：Markdown、公式、代码和工具轨迹都更完整")
        self.workbench_btn.clicked.connect(self.workbench_requested.emit)

        self.rec_btn = QtWidgets.QToolButton(card)
        self.rec_btn.setObjectName("tiny")
        self.rec_btn.setText("录制")
        self.rec_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.rec_btn.setToolTip("录系统声音（不录麦克风）+ 每半分钟一张全屏快照 + 看过哪些窗口，全落今天的库，复盘直接吃；右键：暂停 / 定时停止")
        self.rec_btn.clicked.connect(self.record_toggled.emit)
        self.rec_btn.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.rec_btn.customContextMenuRequested.connect(self._rec_menu)
        self.rec_paused = False

        self.quiz_btn = QtWidgets.QToolButton(card)
        self.quiz_btn.setObjectName("tiny")
        self.quiz_btn.setText("测验")
        self.quiz_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.quiz_btn.setToolTip("AI 根据今天的学习记录出 5 道题考你 —— 在下面输入框里答，它逐题批改")
        self.quiz_btn.clicked.connect(self.quiz_requested.emit)

        self.more_btn = QtWidgets.QToolButton(card)
        self.more_btn.setObjectName("tiny")
        self.more_btn.setText("⋯")
        self.more_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.more_btn.setToolTip("测验 / 历史 / 报告 / 笔记 / 错题本 / 置顶 / 清空 —— 低频的都收在这里")
        self.more_btn.clicked.connect(self._more_menu)

        # 按钮行：**位置必须恒定**。
        # 以前状态文字和按钮挤在同一行，状态一显示（「用了 0.8 秒…」）就把整排按钮往右推
        # 两百像素 ⇒ 用户按记忆中的位置点「新会话」，实际点到了「置顶」。
        # 现在：按钮各占固定宽度、整体靠右；状态文字单独一行放在下面（它会换行，但推不动按钮）。
        # 2026.10 整理：高频的 5 个 + 「⋯」收纳菜单上屏；置顶/清空/历史/测验/低频操作收进菜单，
        # 但控件本体都还在（隐藏）—— 信号、测试、菜单动作照常用它们。
        for btn in (self.top_btn, self.clear_btn, self.history_btn, self.quiz_btn):
            btn.setVisible(False)          # 收进「⋯」菜单的按钮本体
        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addStretch(1)
        for btn in (self.copy_btn, self.star_btn, self.session_btn,
                    self.review_btn, self.workbench_btn, self.rec_btn, self.more_btn):
            btn.setFixedSize(BUTTON_W, BUTTON_H)
            bottom.addWidget(btn)
        box.addLayout(bottom)
        self._sync_top_btn()

        box.addLayout(self.info_row)    # 状态在左、录制在右：长短都推不动上面的按钮

        # 答案面板：高度固定（可拖底边），内容多了在面板内滚动 —— 流式期间不再长高
        self.answer = QtWidgets.QTextBrowser(card)
        self.answer.setObjectName("answer")
        self.answer.setOpenExternalLinks(True)
        self.answer.setFixedHeight(self._answer_h)
        self.answer.setVisible(False)
        box.addWidget(self.answer)

        self.answer_grip = _AnswerGrip(card)
        self.answer_grip.setVisible(False)
        self.answer_grip.moved.connect(self._resize_answer)
        self.answer_grip.released.connect(self._finish_resize)
        box.addWidget(self.answer_grip)

        self.usage_line = QtWidgets.QLabel(card)
        self.usage_line.setObjectName("usage")
        self.usage_line.setWordWrap(False)
        self.usage_line.setFixedHeight(USAGE_H)
        box.addWidget(self.usage_line)

    def _build_pill(self, pill: QtWidgets.QFrame) -> None:
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QtGui.QColor(0, 0, 0, 180))
        pill.setGraphicsEffect(shadow)

        pill.setFixedHeight(PILL_H)
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

    def _compact_card_h(self) -> int:
        """没有答案面板时的卡片高度：输入行 / 按钮行 / 状态行 / 占用行 + 三个间距。"""
        return (CARD_PAD_TOP + CARD_PAD_BOTTOM + ROW_H + BUTTON_H + STATUS_H + USAGE_H
                + 3 * CARD_GAP)

    def _expanded_card_h(self) -> int:
        """有答案面板时：紧凑高度 + 面板 + 拖拽条 + 两个间距。"""
        return self._compact_card_h() + 2 * CARD_GAP + GRIP_H + self._answer_h

    def _apply_geometry(self) -> None:
        """窗口尺寸的唯一出口：只由「收起与否 + 答案面板显隐 + 面板高度」决定。

        不再 `adjustSize()`、不再让布局按内容算尺寸 —— 内容变化永远不触发这里，
        所以流式、状态文字、录制信息都不会让窗口跳。
        """
        if self._collapsed:
            self.card.setVisible(False)
            self.pill.setVisible(True)
            width = config.ASK_BAR_PILL_WIDTH + 2 * BAR_OUTER_X
            height = PILL_H + BAR_OUTER_TOP
        else:
            self.pill.setVisible(False)
            self.card.setVisible(True)
            width = self._full_width() + 2 * BAR_OUTER_X
            card_h = self._expanded_card_h() if self._answer_shown else self._compact_card_h()
            height = card_h + BAR_OUTER_TOP
        size = QtCore.QSize(width, height)
        if self.minimumSize() != size or self.maximumSize() != size:
            self.setFixedSize(size)

    def _resize_answer(self, delta: int) -> None:
        """拖答案底边：只改面板高度，窗口高度跟着固定几何一起算。"""
        if self._drag_base is None:
            self._drag_base = self._answer_h
        height = max(config.ASK_BAR_ANSWER_MIN_H,
                     min(self._drag_base + delta, self._answer_cap))
        if height == self._answer_h:
            return
        self._answer_h = height
        self.answer.setFixedHeight(height)
        self._apply_geometry()

    def _finish_resize(self) -> None:
        self._drag_base = None
        self._save_state()

    def set_collapsed(self, flag: bool) -> None:
        if flag == self._collapsed:
            return
        self._collapsed = flag
        self._apply_geometry()
        self._clamp()
        if not flag:
            self.ask.setFocus(QtCore.Qt.OtherFocusReason)
        self._save_state()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def _place(self) -> None:                      # 兼容旧调用
        self._place_default()

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

    # ---- 状态机 ----
    #
    # 界面的显隐只有这一个入口：答案面板在不在、按钮能不能点、状态行写什么，全走
    # `set_state()`。别处一律不许 `answer.setVisible(...)` / 直接改布局 —— 一散开，
    # 「状态变化奇怪」就会重新长回来。

    def set_state(self, state: str, status: str | None = None) -> None:
        """切换界面状态（idle / thinking / streaming / done / error / history）。"""
        if state not in _STATES:
            raise ValueError(f"未知状态：{state}")
        self._state_name = state
        show_answer = state in _ANSWER_STATES
        if show_answer != self._answer_shown:
            self._answer_shown = show_answer
            self.answer.setVisible(show_answer)
            self.answer_grip.setVisible(show_answer)
            if show_answer:
                self.answer.setFixedHeight(self._answer_h)
            self._apply_geometry()          # 只有面板显隐才动窗口几何
        busy = state in (STATE_THINKING, STATE_STREAMING)
        self.go.setEnabled(not busy)
        self._set_copy_enabled(show_answer and bool(self._last_answer.strip()))
        self._sync_star()
        if status is not None:
            self._set_status(status)

    def _sync_star(self) -> None:
        self.star_btn.setEnabled(self._state_name in (STATE_DONE, STATE_HISTORY)
                                 and self._starrable is not None)

    def _set_status(self, text: str) -> None:
        """状态行：固定一行高，长文按宽度截断，全文放悬停提示。"""
        text = " ".join(str(text or "").split())
        self._status_text = text
        width = max(160, self._full_width() - 2 * CARD_PAD_X - 2)
        if self._rec_text:              # 录制信息占着同一行右侧，先给它让位
            reserve = min(self._full_width() // 2,
                          self.rec_line.fontMetrics().horizontalAdvance(self._rec_text))
            width = max(160, width - reserve - 12)
        shown = self.status.fontMetrics().elidedText(text, QtCore.Qt.ElideRight, width)
        self.status.setText(shown)
        self.status.setToolTip("" if shown == text else text)

    def _set_rec(self, text: str) -> None:
        """录制信息：和状态同一行，靠右；长文截断，全文留在 `_rec_text` 和悬停提示里。"""
        text = " ".join(str(text or "").split())
        self._rec_text = text
        width = max(160, self._full_width() // 2)
        shown = self.rec_line.fontMetrics().elidedText(text, QtCore.Qt.ElideRight, width)
        self.rec_line.setText(shown)
        self.rec_line.setToolTip("" if shown == text else text)

    def _scroll_follow(self) -> None:
        """流式时视图跟着最新内容走；用户往上翻过（_follow=False）就别拽。"""
        if not self._follow:
            return
        bar_sb = self.answer.verticalScrollBar()
        bar_sb.setValue(bar_sb.maximum())

    # ---- 状态切换 ----

    def set_idle(self) -> None:
        """回到「还没问东西」的样子。框选可选，不框也能直接打字问。"""
        self._turns = []
        self._thread = uuid.uuid4().hex[:12]
        self.drop_image()
        self.clear_doc()
        self._reset_answer()
        self._set_status(f"按 {self._tip} 框选提问 · 直接打字也行")

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
        self.quiz_mode = False
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
        self.quiz_mode = False
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
        self.quiz_mode = False
        self._drop_running()          # 旧那一轮（若有）别再往新图的界面上写
        self._image_path = image_path
        self._turns = []
        self._thread = uuid.uuid4().hex[:12]
        self.clear_doc()               # 换了新截图，挂着的文档先摘掉（两者会互相干扰）
        self.thumb.setPixmap(_thumb(shot, THUMB_W, THUMB_H))
        self.thumb.setVisible(True)
        self.go.setEnabled(True)
        self.ask.setPlaceholderText("想问这块屏的什么？（回车发送 · 答完还能接着追问）")
        self._reset_answer()
        if self._collapsed:
            self.set_collapsed(False)
        # 框选时横栏只是被遮罩盖住、没隐藏；遮罩关掉后把焦点收回输入框
        self.raise_()
        self.activateWindow()
        self.ask.setFocus(QtCore.Qt.OtherFocusReason)

    def _reset_answer(self) -> None:
        self.answer.clear()
        self.answer.setPlainText("")        # clear() 再补一道 —— 文档/缓存都归零
        self._streaming = False
        self._activity = ""
        self._answer_start = None
        self._last_answer = ""
        self._showing_history = False
        self._follow = False       # 内容都清了，没什么可跟随的
        self._starrable = None     # 当前内容没了，「收藏」跟着灭
        self.star_btn.setText("收藏")
        # 清空 → 唯一入口回到 idle：面板收起、窗口缩回紧凑几何。
        # 不再 `_force_repaint()` 抖透明度和阴影 —— 几何稳定后没有像素残影可补。
        self.set_state(STATE_IDLE, status="")

    def set_recording(self, on: bool, minutes: float = 0.0, switches: int = 0,
                      detail: str = "") -> None:
        """采集层开着的时候，横栏上给一行「● 录制中 …」—— 让人知道它在记。

        detail 是可选的追加信息（转写字数 / 快照张数 / 没听到声音提示）。
        录制按钮同步换字 + 泛红（role 属性驱动 QSS）。
        """
        self._recording = on
        if on:
            text = f"● 录制中 {minutes:.0f} 分 · 切了 {switches} 次窗口"
            if detail:
                text += f" · {detail}"
            self._set_rec(text)
        else:
            self._set_rec("")
        if self._status_text:           # 右侧让出的宽度变了，状态行重新截一次
            self._set_status(self._status_text)
        self.rec_btn.setText("停止" if on else "录制")   # 「停止录制」四字在 68px 槽里会被截断
        self.rec_btn.setProperty("role", "recording" if on else None)
        style = self.rec_btn.style()
        style.unpolish(self.rec_btn)
        style.polish(self.rec_btn)
        # 录制行常驻固定高度 —— 开关录制只换字，窗口不动

    def refresh_usage(self) -> None:
        """占用数字在后台线程里算 —— walk 整个数据盘会卡界面，别放主线程。

        结果缓存 5 分钟：横栏每次露出来都会走到这儿，不缓存的话数据一多，
        每次 show 都是一次全盘 walk。
        """
        if (self._usage_cache is not None
                and time.monotonic() - self._usage_at < _USAGE_TTL_SECONDS):
            self._apply_usage(self._usage_cache)     # 缓存新鲜：直接上屏，不起线程
            return
        if self._usage_worker is not None and self._usage_worker.isRunning():
            return                             # 上一次还在算，别叠着起
        worker = _UsageWorker(self)
        worker.done.connect(self._apply_usage)
        worker.finished.connect(self._usage_done)
        worker.finished.connect(worker.deleteLater)   # 跑完销毁，别在 bar 底下越攒越多
        self._usage_worker = worker
        worker.start()

    def _usage_done(self) -> None:
        self._usage_worker = None              # 先摘引用再 deleteLater，isRunning 别摸已销毁的

    def _apply_usage(self, info) -> None:
        if isinstance(info, Exception):
            self.usage_line.setText(f"占用没算出来：{info}")
            self.pill_usage.setText("")
            return                             # 失败不缓存 —— 下次显示时再算一次
        self._usage_cache = info
        self._usage_at = time.monotonic()
        self.usage_line.setText(info.line)
        self.usage_line.setToolTip(info.detail)
        self.pill_usage.setText(info.short)
        self.pill.setToolTip(info.detail + chr(10) + "点一下展开 · 拖动可以挪位置")

    def show_message(self, text: str) -> None:
        """状态行写一句话 —— 只换字，不动布局，不重排窗口。"""
        self._set_status(text)

    # ---- 交互 ----

    def showEvent(self, event):
        super().showEvent(event)
        self._answer_cap = self._calc_answer_cap()   # 分辨率/屏幕可能变了，重算
        self._answer_h = max(config.ASK_BAR_ANSWER_MIN_H,
                             min(self._answer_h, self._answer_cap))
        self.answer.setFixedHeight(self._answer_h)
        self._apply_geometry()
        self.refresh_usage()
        self._clamp()
        self.raise_()
        if not self._collapsed:
            self.activateWindow()
            self.ask.setFocus(QtCore.Qt.OtherFocusReason)
        self._topmost(self._on_top)      # 每次露出来都重申一遍层级（别的窗口可能盖过它）

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
        self._last_answer = ""     # 每一轮的答案区都是从头算的 —— 不清的话，流式期间
                                   # 复制会把上一轮答案拼进来，中断时上下文也会被污染
        self._follow = True        # 新一轮从跟随最新内容开始（用户上翻就停，见 _on_chunk）
        cursor.setCharFormat(_answer_char())     # 答案用正常颜色，别接着用蓝底那块的白字
        self.answer.setTextCursor(cursor)
        self._scroll_follow()
        self.set_state(STATE_THINKING)     # 面板显隐只走状态机（这里只是把面板亮出来）

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
        if question.startswith(">"):  # 电脑助手：> 后面是要 AI 帮忙操作电脑的事
            self.computer_request.emit(question[1:].strip())
            self.ask.clear()
            return
        send_text = question
        if self.doc_path:             # 挂了课件：正文随问题一起发
            send_text = f"【参考文档：{self.doc_name}】\n{self.doc_text}\n\n【问题】{question}"
        # 记录开着的时候，把最近几分钟的课堂转写捎给 AI ——「这题老师怎么讲的来着」才答得上
        context = ""
        if self.extra_context_provider is not None:
            try:
                context = self.extra_context_provider() or ""
            except Exception:
                context = ""                 # 上下文拿不到就纯问，别拦着用户
        self._begin_turn(send_text, question, context)
        self.ask.clear()              # 问题已经上屏了 ⇒ 输入框清空，直接打下一句

    def ask_with_context(self, send_text: str, display_text: str, context: str = "",
                         images: list[str] | None = None, mode: str = "",
                         system_override: str = "", use_tools: bool = True) -> None:
        """「程序替用户问」的入口（复盘/测验/电脑助手用）：界面显示 display_text，发给 AI 的是 send_text。

        images = 附加截图（多图），主 image_path 之外最多再带 4 张。
        system_override / use_tools 给非导师任务（比如电脑助手只出 JSON 计划）。
        """
        if self._worker is not None:
            self.show_message("上一句还在写 —— 等它写完再点。")
            return
        if not send_text.strip():
            return
        self._begin_turn(send_text, display_text, context, images, mode,
                         system_override, use_tools)

    def _begin_turn(self, send_text: str, display_text: str, context: str,
                    images: list[str] | None = None, mode: str = "",
                    system_override: str = "", use_tools: bool = True) -> None:
        """开一轮问答：显示 display_text，问 AI 的是 send_text（可带转写上下文）。"""
        self._started_at = time.monotonic()
        self._dots = 0
        self._streaming = False
        self._activity = ""
        self._start_turn(display_text)
        self.set_state(STATE_THINKING, status="在想…")
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(400)
        self._turn_seq += 1           # 开新的一轮：旧的（被掐掉的）回来时靠这个号认出来
        seq = self._turn_seq
        # 这一轮的图/文身份**当场拍死**：答案回来时界面可能已经换过图、甚至清过空，
        # 再读 self._image_path 会把图问答错记成纯文字、连归档截图都丢掉。
        kind = "image" if self._image_path else "text"
        image_path = self._image_path or ""
        self._worker = _AskWorker(self._image_path, send_text, list(self._turns), self,
                                  context=context, extra_images=images)
        # 模式用属性给，不放进构造参数：旧测试里替换的 FakeWorker 只认旧签名，
        # 传 `mode=` 会直接 TypeError。属性赋值对新旧 worker 都无害。
        self._worker._mode = mode or ("quiz" if self.quiz_mode else self.ask_mode)
        self._worker._system_override = system_override
        self._worker._use_tools = use_tools
        self._worker._conversation_key = self._thread
        self._workers.append(self._worker)       # 留着，退出时要 wait（shutdown）
        self._worker.finished.connect(self._reap_workers)
        if hasattr(self._worker, "activity"):
            self._worker.activity.connect(self._on_activity)
        self._worker.chunk.connect(lambda piece, replace, s=seq: self._on_chunk(piece, replace, s))
        self._worker.done.connect(
            lambda text, s=seq, k=kind, p=image_path: self._finish(display_text, text, None, s, k, p))
        self._worker.failed.connect(
            lambda message, s=seq, k=kind, p=image_path: self._finish(display_text, "", message, s, k, p))
        self._worker.start()

    def _on_activity(self, text: str) -> None:
        """后台线程发来的一句话：看图 / 查记录 / 推理中。只更新状态行，不动布局。"""
        self._activity = str(text or "")

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        # 有更具体的动作（查记录 / 看图）就显示它；否则按「先想后写」显示
        label = self._activity or ("正在写" if self._streaming else "在想")
        self._set_status(label + "·" * self._dots
                         + f"  {time.monotonic() - self._started_at:.0f} 秒")

    def _on_chunk(self, piece: str, replace: bool = False, seq: int = 0) -> None:
        """流式：字一到就往答案区追加（已经洗过 Markdown 噪声了）。

        问题那一行是 `_start_turn` 写好的，这里**只动答案那一段**，不能整段清掉。
        `seq` 是这一轮的号 —— 被掐掉的旧轮（清空/新会话/换图）流回来的碎片一律不进界面。
        """
        if seq != self._turn_seq:
            return
        if self._state_name != STATE_STREAMING:
            self.set_state(STATE_STREAMING)     # 只切一次：thinking → streaming 不动几何
        # 插入**之前**看一眼滚动条：用户在底部 = 还在跟着看；上翻过 = 别拽人
        sb = self.answer.verticalScrollBar()
        self._follow = sb.value() >= sb.maximum() - _SCROLL_SLACK
        self._streaming = True
        self._set_copy_enabled(True)
        if replace:
            self._set_answer_part(piece)
        else:
            # 用文档光标插入，**不走** moveCursor —— 那个会顺带把视图拽到底，
            # 用户上翻看旧内容时就被打断（跟随与否交给 _scroll_follow）
            cursor = self.answer.textCursor()
            cursor.movePosition(QtGui.QTextCursor.End)
            cursor.insertText(piece)
            # 追加也要记进 _last_answer：复制按钮只认它，不认整篇文档（不然连「我：」那行一起拷）
            self._last_answer += piece
        # 面板高度固定 ⇒ 没有重排：只把在底部的人的视图滚到最新
        self._scroll_follow()

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

    def _set_answer_markdown(self, text: str) -> None:
        """把答案那一段换成 Markdown 渲染后的富文本。

        流式期间按原文追加（能看见字在长），结束时只重排「答案」这一段，
        上面的问题气泡不动。颜色用深色主题的正文色，避免默认黑色看不清。
        """
        if self._answer_start is None:
            return
        cursor = self.answer.textCursor()
        cursor.setPosition(self._answer_start)
        cursor.movePosition(QtGui.QTextCursor.End, QtGui.QTextCursor.KeepAnchor)
        document = QtGui.QTextDocument()
        # Qt 的 toHtml() 会按文档默认字体写死 font-size；不设就会从 15px 缩回 9pt。
        font = QtGui.QFont("Microsoft YaHei UI")
        font.setPixelSize(15)
        document.setDefaultFont(font)
        document.setDocumentMargin(0)
        document.setDefaultStyleSheet(
            "body { color: #dce4ee; }"
            "h1,h2,h3,h4 { color: #f1f3f4; }"
            "code, pre { color: #f5b74e; font-family: 'Cascadia Mono','Consolas',monospace; }"
            "a { color: #6ea8ff; }"
            "blockquote { color: #aeb7c2; }"
        )
        document.setMarkdown(_markdown_bold_for_qt(text))
        cursor.insertHtml(document.toHtml())
        self._last_answer = text
        self._set_copy_enabled(bool(text.strip()))

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
        self._activity = ""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._worker = None
        self._streaming = False
        ms = int((time.monotonic() - self._started_at) * 1000)
        if error:
            # 只看「答案那一段」有没有写出来的 —— 上面那行「我：」不算
            partial = self._last_answer.strip()
            if partial:
                # 流到一半断了：留着已写出的，底下标一句
                self.set_state(STATE_ERROR, status=f"回答中断 —— {error}")
                # 已写出的那段也算上下文 —— 不然追问「继续」时 AI 记不得自己说过啥
                self._turns.append((question, partial))
            else:
                self._set_answer_part(error)
                self.set_state(STATE_ERROR, status="没成功 —— 改一下再问")
        else:
            self._set_answer_markdown(text)      # 完整答案用 Markdown 渲染一次
            self._turns.append((question, text))
            if kind == "image":
                status = f"用了 {ms / 1000:.1f} 秒 · 还想追问就直接再打字（看的还是这张图）"
            else:
                status = f"用了 {ms / 1000:.1f} 秒 · 还想追问就直接再打字"
            self.set_state(STATE_DONE, status=status)
            self.answered.emit({
                "question": question,
                "answer": text,
                "ms": ms,
                "kind": kind,
                "image_path": image_path,
                "thread": self._thread,
            })
        self._scroll_follow()
        self.ask.setFocus(QtCore.Qt.OtherFocusReason)

    def _rec_menu(self, pos) -> None:
        """录制按钮右键：暂停/继续 + 定时停止（不用再加按钮占位置）。"""
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(QSS)
        menu.addAction("继续录制" if self.rec_paused else "暂停录制",
                       self.rec_pause_toggled.emit)
        timer_menu = menu.addMenu("定时停止")
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
            self._set_rec("⏸ 已暂停 —— 右键「录制」继续")
        else:
            self._set_rec("● 继续录制")

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
