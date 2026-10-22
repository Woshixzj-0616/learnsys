"""界面状态机与内容复位：状态显隐、清空/新会话/换图、录制与占用。"""
from __future__ import annotations

import time
import uuid

from PySide6 import QtCore

from learnsys import config
from .common import (CARD_PAD_X, STATE_DONE, STATE_HISTORY, STATE_IDLE,
                     STATE_STREAMING, STATE_THINKING, _ANSWER_STATES, _STATES,
                     _USAGE_TTL_SECONDS, _thumb, THUMB_H, THUMB_W)
from .workers import _UsageWorker


class StateMixin:
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
        self._stream_text = ""
        self._thinking_text = ""
        self._last_thinking = ""
        self._answer_view = "answer"
        self._view_pinned = False
        if self._render_timer.isActive():
            self._render_timer.stop()
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
