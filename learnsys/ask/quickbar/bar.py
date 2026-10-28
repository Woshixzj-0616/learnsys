"""快捷栏主体：信号 + 初始化。

行为按职责拆在 layout / state / streaming / actions / build 几个 mixin 里，
对外仍然只有这一条横栏（`from learnsys.ask.bar import AskBar`）。
"""
from __future__ import annotations

import uuid

from PySide6 import QtCore, QtWidgets

from learnsys import config, product
from learnsys.ask import icon as icon_mod
from .actions import ActionsMixin
from .build import BuildMixin
from .common import STATE_IDLE, resolve_on_top
from .layout import LayoutMixin
from .state import StateMixin
from .streaming import StreamMixin
from .workers import _AskWorker


class AskBar(BuildMixin, LayoutMixin, StateMixin, StreamMixin, ActionsMixin,
             QtWidgets.QWidget):
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
    open_link_requested = QtCore.Signal(str)   # 答案区里的 `#/...` 深链 → app 打开工作台页面

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
        self._stream_text = ""        # 这一轮流式累积的答案原文
        self._thinking_text = ""      # 这一轮流式累积的思考原文
        self._last_thinking = ""      # 最近一轮的思考（点「查看思考过程」用）
        self._answer_view = "answer"  # answer / thinking —— 答案面板现在显示哪一面
        self._view_pinned = False     # 用户手动点过切换：别被流式自动切回去
        self._last_render_at = 0.0
        self._render_timer = QtCore.QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._flush_stream_render)
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
        # 旧文件没有 always_on_top_set 标记 ⇒ 视作历史残留，用 config 默认（见 resolve_on_top）。
        self._on_top = resolve_on_top(self._state, config.ASK_BAR_ALWAYS_ON_TOP)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(f"{product.PRODUCT_NAME} · {product.QNA_NAME}快捷栏")
        self.setWindowIcon(icon_mod.icon())
        self._apply_flags()
        self._build()
        self._restore_place()
        self.set_idle()

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def set_capture_excluded(self, excluded: bool) -> bool:
        """录像时把横栏排除在屏幕捕获之外（Windows 10 2004+ 的 WDA_EXCLUDEFROMCAPTURE）。

        用户要能一直点「停止」，所以横栏不能藏；但也不能出现在视频里。
        这个 API 对 mss/BitBlt 实测有效（2026-10-25 本机验证）；老系统失败时返回 False，
        横栏会留在画面里，不影响录像本身。
        """
        try:
            import ctypes
            value = 0x11 if excluded else 0x00   # WDA_EXCLUDEFROMCAPTURE / WDA_NONE
            return bool(ctypes.windll.user32.SetWindowDisplayAffinity(
                int(self.winId()), value))
        except Exception:
            return False
