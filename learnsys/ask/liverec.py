"""「录像」的一次会话：画面 + 系统声音 + 转写 + 窗口时间线。

- 画面与声音走 `services.video_recorder`：主屏 10 fps、H.264 + AAC、标准 MP4。
- 声音同时降到 16k 单声道，按 45 秒一块交给本地 whisper；文本落今天的库。
- 窗口那一路沿用 `record.WindowRecorder`，和录像共用一个 session。
- MP4 是唯一原件；转写、SRT、幻灯片都由它派生。
- 第一次转写要先加载 whisper（十几秒），视频照录，不影响。
"""
from __future__ import annotations

import datetime
import pathlib
import queue
import threading

import numpy as np
from PySide6 import QtCore

from learnsys import asr, config, record, store
from learnsys.services.video_recorder import VideoRecorder, recording_dir

_transcriber = None          # 进程级常驻：加载一次，反复录像不用再等


def _get_transcriber() -> asr.Transcriber:
    global _transcriber
    if _transcriber is None:
        _transcriber = asr.Transcriber(
            config.ASR_MODEL_DIR, config.ASR_DEVICE, config.ASR_COMPUTE_TYPE,
            config.ASR_LANGUAGE, config.HOTWORDS, config.ASR_BEAM_SIZE, config.ASR_VAD,
        )
    return _transcriber


def _parse_started(value: str) -> datetime.datetime:
    try:
        return datetime.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.datetime.now()


class LiveRecorder(QtCore.QObject):
    """一次录像 = 一个 session：视频 + 声音转写 + 窗口事件。"""

    ticked = QtCore.Signal()          # 每秒：界面刷新「录像中 X 分 · 转写 N 字」
    info = QtCore.Signal(str)         # 模型加载 / 出错等一句话消息
    saved = QtCore.Signal(dict)       # 视频已落盘、库已更新（转写可能还在后台跑）
    stopped = QtCore.Signal(dict)     # 全部收尾完成（含最后一块转写）

    def __init__(self, conn_getter, parent=None):
        super().__init__(parent)
        self._conn_getter = conn_getter
        self.window_rec = record.WindowRecorder(conn_getter, self)
        self.window_rec.ticked.connect(self.ticked)
        self._chunks: queue.Queue = queue.Queue()
        self._asr_thread: threading.Thread | None = None
        self._session_id: int | None = None
        self._finishing = False
        self.paused = False
        self.video: VideoRecorder | None = None
        self.slide_saved = None         # app 塞的：录像里的幻灯片落盘后进 OCR 队列
        self._slide_session_id = 0
        self._chars = 0
        self._transcripts = 0
        self._folder: pathlib.Path | None = None
        self._stop_timer = QtCore.QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._on_stop_timer)

    # ---- 状态 ----

    @property
    def recording(self) -> bool:
        return self._session_id is not None or self._finishing

    @property
    def chars(self) -> int:
        return self._chars

    @property
    def transcripts(self) -> int:
        return self._transcripts

    @property
    def frames(self) -> int:
        """本次存下的幻灯片张数（旧版是快照张数，界面沿用这个属性名）。"""
        return len(self.video.slides) if self.video is not None else 0

    @property
    def finishing(self) -> bool:
        return self._finishing

    @property
    def listening(self) -> bool:
        """最近一块有没有声音（电平表）。"""
        return bool(self.video is not None and self.video.listening)

    @property
    def duration(self) -> float:
        return self.video.duration if self.video is not None else 0.0

    @property
    def bytes(self) -> int:
        return self.video.bytes if self.video is not None else 0

    @property
    def session_id(self) -> int:
        """当前/刚结束的会话 id（收尾期间也返回，页面用它定位）。"""
        return int(self._session_id or self._slide_session_id or 0)

    def set_paused(self, paused: bool) -> None:
        """暂停 = 视频时钟冻结、声音块丢弃、窗口事件不记；恢复后时间轴连续。"""
        self.paused = paused
        self.window_rec.paused = paused
        if self.video is not None:
            if paused:
                self.video.pause()
            else:
                self.video.resume()
        self.info.emit("已暂停录像 —— 右键「录像」继续。" if paused else "继续录像。")

    def set_stop_timer(self, minutes: int) -> None:
        """定时停止：minutes=0 取消。"""
        if minutes <= 0:
            self._stop_timer.stop()
            self.info.emit("已取消定时停止。")
            return
        self._stop_timer.start(int(minutes * 60 * 1000))
        self.info.emit(f"将在 {minutes} 分钟后自动停止录像。")

    def _on_stop_timer(self) -> None:
        if self.recording:
            self.info.emit("定时时间到 —— 自动停止录像。")
            self.stop()

    # ---- 开 / 停 ----

    def start(self) -> None:
        if self.recording:
            return
        conn = self._conn_getter()
        session_id = store.start_session(conn)
        self._session_id = session_id
        row = conn.execute("SELECT started_at FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
        started = _parse_started(row[0] if row else store.now())
        folder = recording_dir(config.VIDEO_DIR, started, session_id)
        folder.mkdir(parents=True, exist_ok=True)
        self._folder = folder
        self._chars = 0
        self._transcripts = 0
        self.paused = False
        self.window_rec.paused = False
        self._chunks = queue.Queue()          # 上一段的 None 哨兵别带进这一段
        self._slide_session_id = session_id
        self.video = VideoRecorder(
            out_path=folder / "video.mp4",
            fps=config.VIDEO_FPS,
            max_width=config.VIDEO_MAX_WIDTH,
            chunk_seconds=config.CHUNK_SECONDS,
            slides_dir=folder / "幻灯片",
            thumb_path=folder / "thumb.jpg",
            asr_chunks=self._chunks,
            on_slide=self._on_slide,
            on_info=self.info.emit,
        )
        self.video.started_at = started
        try:
            self.video.start()
        except Exception as exc:
            self.video = None
            self._session_id = None
            try:
                store.end_session(conn, session_id)
            except Exception:
                pass
            self.info.emit(f"录像起不来：{exc}")
            return
        self._asr_thread = threading.Thread(
            target=self._asr_loop, name="asr", daemon=True,
            args=(session_id,))
        self._asr_thread.start()
        self.window_rec.start(session_id)            # 窗口那路接管同一个 session
        self.info.emit("开始录像 —— 声音在录、画面在录；转写模型第一次要加载十几秒。")

    def stop(self) -> None:
        """收摊：采集立刻停；视频收尾和最后一块转写在后台跑，不卡界面。"""
        if self._session_id is None or self._finishing:
            return
        self._finishing = True
        session_id = self._session_id
        self._session_id = None
        self._stop_timer.stop()
        window_summary = self.window_rec.stop()       # 内部会 end_session
        video = self.video
        self.video = None
        folder = self._folder

        def finalize() -> None:
            # ① 先停视频、写库、发 saved —— 页面能立刻播放；转写在后台继续。
            video_summary = video.stop() if video is not None else {}
            duration = float(video_summary.get("录像秒数") or 0)
            try:
                conn = self._conn_getter()
                store.update_video(
                    conn, session_id,
                    title=store.recording_title(
                        str(video_summary.get("开始时间") or store.now())),
                    video_path=str(video_summary.get("录像路径") or ""),
                    video_bytes=int(video_summary.get("录像字节") or 0),
                    duration_ms=int(round(duration * 1000)),
                    thumb_path=str(video_summary.get("缩略图") or ""),
                    slides_dir=str(video_summary.get("幻灯片目录") or ""),
                )
            except Exception as exc:
                self.info.emit(f"录像信息没写进库：{exc}")
            summary = dict(window_summary or {})
            summary.update(video_summary)
            summary["会话"] = session_id
            summary["录像目录"] = str(folder or "")
            summary["转写条数"] = 0
            summary["转写字数"] = 0
            self.saved.emit(dict(summary))
            # ② 再等最后一块转写 —— 失败/慢都不影响已经落盘的视频。
            if self._asr_thread is not None:
                self._asr_thread.join(timeout=120)    # 最后一块 45 秒 + 转写，等得起
                self._asr_thread = None
            summary["转写条数"] = self._transcripts
            summary["转写字数"] = self._chars
            self._finishing = False
            self.ticked.emit()
            self.stopped.emit(summary)

        threading.Thread(target=finalize, name="rec-finalize", daemon=True).start()

    # ---- 转写 ----

    def _asr_loop(self, session_id: int) -> None:
        """转写线程：静音块跳过 → whisper → 落库。"""
        try:
            tr = _get_transcriber()
        except Exception as exc:                      # 模型构造失败别让线程无声死掉
            self.info.emit(f"转写起不来：{exc} —— 视频和声音还在 MP4 里。")
            return
        if not tr.load():
            self.info.emit(f"转写模型加载失败：{tr.load_error} —— 视频和声音还在 MP4 里。")
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

    def _on_slide(self, path: str, ts: str) -> None:
        """幻灯片落盘 → OCR 队列（文字进 frame_text，按 session 可查）。"""
        if self.slide_saved is not None:
            try:
                self.slide_saved(path, ts, self._slide_session_id)
            except Exception:
                pass
