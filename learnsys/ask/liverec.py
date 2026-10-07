"""「录制」按钮的三路编排：窗口事件 + 系统声音转写 + 全屏快照，一按全开。

- 声音走 **系统回环**（WASAPI loopback，戴耳机也能录），45 秒一块交给本地
  whisper 转写，文本落今天的库 —— 复盘 / 追问上下文直接就能吃。
- 快照每 ASK_FRAME_SECONDS 秒一张全屏 JPEG，落 今天的「录屏」文件夹（不是视频，
  是快照序列 —— 够复盘用，体积小两个数量级；真视频以后想要再说）。
- 转写模型第一次录制时才加载（十几秒），之后常驻 —— 反复录制不用等。
- 线程口径：音频采集 / 转写各一条后台线程（沿用学习记录器验证过的模式），
  快照用 Qt 定时器在主线程抓（grabWindow 很快，不卡界面）。
"""
from __future__ import annotations

import datetime
import pathlib
import queue
import threading

import numpy as np
from PySide6 import QtCore, QtGui

from learnsys import asr, audio, config, record, store

_transcriber = None          # 进程级常驻：加载一次，反复录制不用再等
_transcriber_error = ""


def _get_transcriber() -> asr.Transcriber:
    global _transcriber
    if _transcriber is None:
        _transcriber = asr.Transcriber(
            config.ASR_MODEL_DIR, config.ASR_DEVICE, config.ASR_COMPUTE_TYPE,
            config.ASR_LANGUAGE, config.HOTWORDS, config.ASR_BEAM_SIZE, config.ASR_VAD,
        )
    return _transcriber


def frame_dir(when=None) -> pathlib.Path:
    """今天的屏幕快照放哪儿。"""
    return config.day_dir(when) / "录屏"


def grab_all_screens_image() -> QtGui.QImage | None:
    """所有屏拼成一张 QImage（和框选抓屏同一套拼法）；抓不到返回 None。"""
    screens = QtGui.QGuiApplication.screens()
    if not screens:
        return None
    area = QtCore.QRect()
    for screen in screens:
        area = area.united(screen.geometry())
    canvas = QtGui.QImage(area.width(), area.height(), QtGui.QImage.Format.Format_ARGB32)
    canvas.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(canvas)
    for screen in screens:
        geo = screen.geometry()
        one = screen.grabWindow(0, 0, 0, geo.width(), geo.height())
        if one.isNull():
            continue
        painter.drawImage(geo.x() - area.x(), geo.y() - area.y(), one.toImage())
    painter.end()
    if canvas.isNull() or canvas.width() == 0:
        return None
    return canvas


class LiveRecorder(QtCore.QObject):
    """一次录制 = 一个 session：窗口（record.WindowRecorder）+ 声音转写 + 快照。"""

    ticked = QtCore.Signal()          # 每秒：界面刷新「录制中 X 分 · 转写 N 字」
    info = QtCore.Signal(str)         # 模型加载 / 出错等一句话消息
    stopped = QtCore.Signal(dict)     # 结束汇总

    def __init__(self, conn_getter, parent=None):
        super().__init__(parent)
        self._conn_getter = conn_getter
        self.window_rec = record.WindowRecorder(conn_getter, self)
        self.window_rec.ticked.connect(self.ticked)
        self._chunks: queue.Queue = queue.Queue()
        self.audio = audio.LoopbackRecorder(self._chunks, chunk_seconds=config.CHUNK_SECONDS)
        self._asr_thread: threading.Thread | None = None
        self._session_id: int | None = None
        self._finishing = False
        self.paused = False
        self._frames = 0
        self._chars = 0
        self._transcripts = 0
        self.frame_paths: list[str] = []   # 本次录制存的快照（复盘挑几张喂 AI 用）
        self._stop_timer = QtCore.QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._on_stop_timer)
        self._frame_timer = QtCore.QTimer(self)
        self._frame_timer.setInterval(max(5000, int(config.ASK_FRAME_SECONDS * 1000)))
        self._frame_timer.timeout.connect(self._grab_frame)

    # ---- 状态 ----

    @property
    def recording(self) -> bool:
        return self._session_id is not None or self._finishing

    @property
    def frames(self) -> int:
        return self._frames

    @property
    def chars(self) -> int:
        return self._chars

    @property
    def transcripts(self) -> int:
        return self._transcripts

    @property
    def finishing(self) -> bool:
        return self._finishing

    @property
    def listening(self) -> bool:
        """最近半秒有没有听到声音（电平表）。"""
        return self.audio.level >= config.SILENCE_RMS

    def set_paused(self, paused: bool) -> None:
        """暂停 = 三路都停手但不结束会话：声音块直接丢弃、不抓快照、不记窗口。"""
        self.paused = paused
        self.window_rec.paused = paused
        self.info.emit("已暂停录制 —— 右键「录制」继续。" if paused else "继续录制。")

    def set_stop_timer(self, minutes: int) -> None:
        """定时停止：minutes=0 取消。"""
        if minutes <= 0:
            self._stop_timer.stop()
            self.info.emit("已取消定时停止。")
            return
        self._stop_timer.start(int(minutes * 60 * 1000))
        self.info.emit(f"将在 {minutes} 分钟后自动停止录制。")

    def _on_stop_timer(self) -> None:
        if self.recording:
            self.info.emit("定时时间到 —— 自动停止录制。")
            self.stop()

    # ---- 开 / 停 ----

    def start(self) -> None:
        if self.recording:
            return
        conn = self._conn_getter()
        self._session_id = store.start_session(conn)
        self.frame_paths = []
        self._frames = 0
        self._chars = 0
        self._transcripts = 0
        self.window_rec.start(self._session_id)      # 窗口那路接管同一个 session
        self.audio = audio.LoopbackRecorder(self._chunks, chunk_seconds=config.CHUNK_SECONDS)
        self.audio.start()                            # 声音那路（内部自己抓回环设备）
        self._asr_thread = threading.Thread(
            target=self._asr_loop, name="asr", daemon=True, args=(self._session_id,))
        self._asr_thread.start()
        self._frame_timer.start()
        self._grab_frame()                            # 开录先来一张，别空窗
        self.info.emit("开始录制 —— 转写模型第一次要加载十几秒，稍等。")

    def stop(self) -> None:
        """收摊：采集三路立刻停；转写线程在后台把最后一块吐完再汇报（**不卡界面**）。

        最终汇总走 stopped 信号 —— 期间 recording 仍是 True（收尾中不许再开新的，
        两个转写线程会抢同一个队列）。
        """
        if self._session_id is None or self._finishing:
            return
        self._frame_timer.stop()
        self._finishing = True
        session_id = self._session_id
        self._session_id = None
        window_summary = self.window_rec.stop()       # 内部会 end_session
        self.audio.stop()                             # 线程退出时往队列塞 None 哨兵

        def finalize() -> None:
            if self._asr_thread is not None:
                self._asr_thread.join(timeout=120)    # 最后一块 45 秒 + 转写，等得起
                self._asr_thread = None
            summary = dict(window_summary or {})
            # 用自己累计的数（落库时 +1）—— 事后重查库有竞态，真机汇总里少报过转写
            summary["转写条数"] = self._transcripts
            summary["转写字数"] = self._chars
            summary["快照张数"] = self._frames
            summary["快照目录"] = str(frame_dir())
            self._finishing = False
            self.ticked.emit()
            self.stopped.emit(summary)

        threading.Thread(target=finalize, name="rec-finalize", daemon=True).start()

    # ---- 三路 internals ----

    def _asr_loop(self, session_id: int) -> None:
        """转写线程：和学习记录器同一条验证过的链路（静音跳过 → whisper → 落库）。"""
        try:
            tr = _get_transcriber()
        except Exception as exc:                      # 模型构造失败别让线程无声死掉
            self.info.emit(f"转写起不来：{exc}")
            return
        if not tr.load():
            self.info.emit(f"转写模型加载失败：{tr.load_error} —— 声音这路只录不转")
            # 继续把队列喝干，别让哨兵没人收
        while True:
            item = self._chunks.get()
            if item is None:
                return
            started, samples = item
            if samples.size < config.MIN_CHUNK_SECONDS * 16000:
                continue
            if self.paused:               # 暂停中：块直接丢，不花转写算力
                continue
            rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
            if rms < config.SILENCE_RMS:
                continue
            for s, e, text in tr.transcribe(samples):
                ts_start = store.stamp(started + datetime.timedelta(seconds=s))
                ts_end = store.stamp(started + datetime.timedelta(seconds=e))
                try:
                    store.add_transcript(self._conn_getter(), session_id, ts_start, ts_end, text)
                except Exception as exc:
                    self.info.emit(f"转写落库失败：{exc}")
                    return
                self._chars += len(text)
                self._transcripts += 1
                self.ticked.emit()

    def _grab_frame(self) -> None:
        """全屏快照：JPEG 落「录屏」文件夹。"""
        if self.paused:
            return
        canvas = grab_all_screens_image()
        if canvas is None:
            return
        folder = frame_dir()
        folder.mkdir(parents=True, exist_ok=True)
        name = f"frame_{datetime.datetime.now():%H%M%S}_{self._frames:04d}.jpg"
        if canvas.save(str(folder / name), "JPEG", 80):
            self._frames += 1
            path = str(folder / name)
            self.frame_paths.append(path)
            saved = getattr(self, "frame_saved", None)
            if saved is not None:
                saved(path, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self.ticked.emit()
