"""界面构建：卡片、小条与固定几何。"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from learnsys import product
from .common import (BAR_OUTER_TOP, BAR_OUTER_X, BUTTON_H, BUTTON_W, CARD_GAP,
                     CARD_PAD_BOTTOM, CARD_PAD_TOP, CARD_PAD_X, GRIP_H, PILL_H,
                     QSS, REC_H, ROW_H, STATUS_H, THUMB_H, THUMB_W, USAGE_H)
from .workers import _AnswerGrip


class BuildMixin:
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
        self.review_btn.setToolTip("拿今天记录的窗口和课堂转写问 AI：我刚才学了什么？（要先在托盘「开始录像」）")
        self.review_btn.clicked.connect(self.review_requested.emit)

        self.workbench_btn = QtWidgets.QToolButton(card)
        self.workbench_btn.setObjectName("tiny")
        self.workbench_btn.setText("工作台")
        self.workbench_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.workbench_btn.setToolTip(f"在独立窗口里打开{product.PRODUCT_NAME}：Markdown、公式、代码和工具轨迹都更完整")
        self.workbench_btn.clicked.connect(self.workbench_requested.emit)

        self.rec_btn = QtWidgets.QToolButton(card)
        self.rec_btn.setObjectName("tiny")
        self.rec_btn.setText("录像")
        self.rec_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.rec_btn.setToolTip(
            "录主屏 + 系统声音（不录麦克风），存成 MP4 到「录像」文件夹；"
            "停止后可播放、导出、打开文件夹。右键：暂停 / 定时停止")
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
        self.answer.setOpenExternalLinks(False)   # 自己处理：think: 切视图，http 交给系统浏览器
        self.answer.anchorClicked.connect(self._on_answer_anchor)
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
        self.pill_title = QtWidgets.QLabel(product.PRODUCT_NAME, pill)
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
