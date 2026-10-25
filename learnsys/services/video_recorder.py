"""屏幕录像引擎：mss 抓主屏 + WASAPI 回环 + PyAV 合成标准 MP4。

纯 Python，不依赖 Qt；界面层通过回调拿状态。

口径（2026-10-25 拍板）：
- 主屏、10 fps、最长边 1600；H.264 + AAC，标准 MP4（分片写，异常退出也尽量能开）。
- 声音只录**系统输出**（WASAPI loopback），不录麦克风。
- 声音一份进 AAC；另一份降到 16k 单声道，按 `CHUNK_SECONDS` 交给 whisper。
- 暂停 = 视频时钟冻结、音频丢弃；恢复后时间轴连续，转写时间戳与视频一致。
- 无声时 loopback 的 `read()` 会阻塞：停止时从别的线程 `stop_stream()` 解锁，
  写入端按墙上时钟补静音，避免声画漂移。

测试用注入的 `screen_source` / `audio_source`，不在 CI 里碰真实屏幕和声卡。
"""
from __future__ import annotations

import datetime
import fractions
import pathlib
import queue
import threading
import time

import numpy as np

from learnsys import config
from learnsys.audio import to_mono_16k
from .video_sources import (Clock, DEFAULT_MAX_WIDTH, LoopbackSource,
                            RecorderError, ScreenSource, fit_size)

DEFAULT_FPS = 10
AUDIO_RATE = 48000
AUDIO_BITRATE = 96000
ASR_RATE = 16000
MIN_ASR_SECONDS = 2.0
SLIDE_INTERVAL = 10.0
SLIDE_MAX = 240
SLIDE_DIFF = 8.0          # 32×32 灰度平均差超过这个才算换页


def recording_dir(root: pathlib.Path, started_at: datetime.datetime,
                  session_id: int) -> pathlib.Path:
    """一段录像的文件夹：`录像/20261025-140312-12/`。"""
    return pathlib.Path(root) / f"{started_at:%Y%m%d-%H%M%S}-{int(session_id)}"


class VideoRecorder:
    """一次录像 = 采集两条线程 + 一条写盘线程；停止后可拿汇总。"""

    def __init__(
        self,
        *,
        out_path: pathlib.Path,
        fps: int = DEFAULT_FPS,
        max_width: int = DEFAULT_MAX_WIDTH,
        chunk_seconds: float = 45.0,
        slides_dir: pathlib.Path | None = None,
        thumb_path: pathlib.Path | None = None,
        asr_chunks: queue.Queue | None = None,
        on_slide=None,
        on_info=None,
        screen_source=None,
        audio_source=None,
        slide_interval: float = SLIDE_INTERVAL,
    ) -> None:
        self.out_path = pathlib.Path(out_path)
        self.fps = max(2, int(fps))
        self.max_width = max(320, int(max_width))
        self.chunk_seconds = max(5.0, float(chunk_seconds))
        self.slides_dir = pathlib.Path(slides_dir) if slides_dir else None
        self.thumb_path = pathlib.Path(thumb_path) if thumb_path else None
        self.asr_chunks = asr_chunks
        self.on_slide = on_slide
        self.on_info = on_info
        self.slide_interval = max(2.0, float(slide_interval))

        self.clock = Clock()
        self.started_at = datetime.datetime.now()
        self.level = 0.0
        self.error = ""
        self.slides: list[str] = []
        self.dropped = 0
        self.frames = 0
        self.audio_ok = False

        self._screen = screen_source or ScreenSource(self.max_width)
        self._audio = audio_source or LoopbackSource()
        self._vq: queue.Queue = queue.Queue(maxsize=3)
        self._aq: queue.Queue = queue.Queue(maxsize=120)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._producers_done = threading.Event()
        self._end_time: float | None = None
        self._started = False
        self._threads: list[threading.Thread] = []
        self._container = None
        self._vstream = None
        self._astream = None
        self._out_size = (2, 2)
        self._last_frame = None
        self._last_fp = None
        self._next_slide_check = 0.0
        self._thumb_done = False
        self._next_video_pts = 0
        self._next_audio_pts = 0
        self._asr_buf: list[np.ndarray] = []
        self._asr_start: float | None = None
        self._asr_expected: float | None = None
        self._asr_samples = 0
        self._asr_sent = False
        self._summary_lock = threading.Lock()
        self._stopped = False

    # ---- 状态 ----

    @property
    def recording(self) -> bool:
        return self._started and not self._stop.is_set()

    @property
    def duration(self) -> float:
        value = self._end_time if self._end_time is not None else self.clock.now()
        return round(value, 1)

    @property
    def bytes(self) -> int:
        try:
            return int(self.out_path.stat().st_size)
        except OSError:
            return 0

    @property
    def listening(self) -> bool:
        return self.level >= config.SILENCE_RMS

    # ---- 开 / 停 ----

    def start(self) -> None:
        if self._started:
            return
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        if self.slides_dir is not None:
            self.slides_dir.mkdir(parents=True, exist_ok=True)
        width, height = self._screen.open()
        self._out_size = fit_size(width, height, self.max_width)
        try:
            self._audio.open()
            self.audio_ok = True
        except Exception as exc:
            self.audio_ok = False
            self._audio.close()
            self._info(f"{exc} —— 这一段只录画面。")
        try:
            self._open_container()
        except Exception:
            self._screen.close()
            self._audio.close()
            raise
        self._started = True
        for target, name in ((self._capture_loop, "video-capture"),
                             (self._audio_loop, "video-audio"),
                             (self._writer_loop, "video-writer")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> dict:
        """停止并收尾；可以在后台线程里调用。重复调用返回同一份汇总。"""
        with self._summary_lock:
            if self._stopped:
                return self._summary()
            self._stopped = True
        self._stop.set()
        self._audio.stop()                 # 解开阻塞中的回环 read()
        for thread in self._threads[:2]:
            thread.join(timeout=5)
        self._end_time = self.clock.now()
        self._producers_done.set()         # 告诉写盘线程：不会再有新块了
        for thread in self._threads[2:]:
            thread.join(timeout=30)
        self._screen.close()
        self._audio.close()
        if any(thread.is_alive() for thread in self._threads):
            self.error = self.error or "收尾超时：文件可能不完整"
        self._started = False
        return self._summary()

    def pause(self) -> None:
        self._paused.set()
        self.clock.pause()

    def resume(self) -> None:
        self._paused.clear()
        self.clock.resume()

    # ---- 写盘 ----

    def _open_container(self) -> None:
        import av
        try:
            self._container = av.open(
                str(self.out_path), mode="w",
                options={"movflags": "frag_keyframe+empty_moov"})
            self._vstream = self._container.add_stream("libx264", rate=self.fps)
            self._vstream.width, self._vstream.height = self._out_size
            self._vstream.pix_fmt = "yuv420p"
            self._vstream.options = {
                "preset": "veryfast", "crf": "26", "g": str(self.fps * 2)}
            if self.audio_ok:
                self._astream = self._container.add_stream("aac", rate=AUDIO_RATE)
                self._astream.layout = "stereo"
                self._astream.bit_rate = AUDIO_BITRATE
        except Exception as exc:
            self.error = f"编码器没打开：{type(exc).__name__}: {exc}"
            raise RecorderError(self.error) from exc

    def _encode_video(self, arr: np.ndarray, pts: int) -> None:
        import av
        frame = av.VideoFrame.from_ndarray(arr, format="bgr24")
        if (frame.width, frame.height) != self._out_size:
            frame = frame.reformat(width=self._out_size[0],
                                   height=self._out_size[1], format="yuv420p")
        else:
            frame = frame.reformat(format="yuv420p")
        frame.pts = pts
        for packet in self._vstream.encode(frame):
            self._container.mux(packet)
        self.frames += 1

    def _encode_silence(self, samples: int, pts: int) -> int:
        if self._astream is None or samples <= 0:
            return pts
        import av
        remaining = samples
        cursor = pts
        while remaining > 0:
            take = min(remaining, AUDIO_RATE)
            data = np.zeros((2, take), dtype=np.float32)
            frame = av.AudioFrame.from_ndarray(data, format="fltp", layout="stereo")
            frame.sample_rate = AUDIO_RATE
            frame.pts = cursor
            frame.time_base = fractions.Fraction(1, AUDIO_RATE)
            for packet in self._astream.encode(frame):
                self._container.mux(packet)
            cursor += take
            remaining -= take
        return cursor

    def _encode_audio(self, arr: np.ndarray, rate: int, pts: int) -> int:
        if self._astream is None:
            return pts
        import av
        x = np.asarray(arr, dtype=np.float32)
        if x.ndim == 1:
            x = x[:, None]
        if x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)
        elif x.shape[1] > 2:
            x = x[:, :2]
        if rate != AUDIO_RATE and x.shape[0]:
            count = int(x.shape[0] * AUDIO_RATE / rate)
            index = (np.arange(count) * rate / AUDIO_RATE).astype(np.int64)
            index = np.clip(index, 0, x.shape[0] - 1)
            x = x[index]
        data = np.ascontiguousarray(x.T)
        frame = av.AudioFrame.from_ndarray(data, format="fltp", layout="stereo")
        frame.sample_rate = AUDIO_RATE
        frame.pts = pts
        frame.time_base = fractions.Fraction(1, AUDIO_RATE)
        for packet in self._astream.encode(frame):
            self._container.mux(packet)
        return pts + int(data.shape[1])

    # ---- 采集线程 ----

    def _capture_loop(self) -> None:
        interval = 1.0 / self.fps
        next_tick = self.clock.now()
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                next_tick = self.clock.now()
                continue
            now = self.clock.now()
            if now < next_tick:
                time.sleep(min(next_tick - now, 0.02))
                continue
            arr = self._screen.read()
            if arr is None:
                time.sleep(0.05)
                continue
            pts = int(now * self.fps)
            self._last_frame = arr
            self._maybe_thumb(arr)
            self._maybe_slide(arr, now)
            try:
                self._vq.put_nowait((pts, arr))
            except queue.Full:
                self.dropped += 1
            next_tick = now + interval

    def _audio_loop(self) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                self._flush_asr()
                time.sleep(0.05)
                continue
            item = self._audio.read()
            if item is None:
                if self._stop.is_set():
                    break
                time.sleep(0.05)
                continue
            arrived, x = item
            self.level = self._audio.level
            duration = float(x.shape[0]) / max(1, self._audio.rate)
            start = max(0.0, self.clock.now() - duration)
            if self._astream is not None:
                try:
                    self._aq.put_nowait((start, x, self._audio.rate))
                except queue.Full:
                    self.dropped += 1
            mono = to_mono_16k(x, self._audio.rate)
            self._push_asr(mono, start, duration)
        self._flush_asr()
        if self.asr_chunks is not None and not self._asr_sent:
            self.asr_chunks.put(None)
            self._asr_sent = True

    def _writer_loop(self) -> None:
        try:
            while not (self._producers_done.is_set()
                       and self._vq.empty() and self._aq.empty()):
                self._drain_video()
                self._drain_audio()
                if self._vq.empty() and self._aq.empty():
                    time.sleep(0.005)
            # 停止时把最后一段补齐，保证音画时长一致
            end = self._end_time if self._end_time is not None else self.clock.now()
            if self._last_frame is not None:
                target = int(end * self.fps)
                while self._next_video_pts <= target:
                    self._encode_video(self._last_frame, self._next_video_pts)
                    self._next_video_pts += 1
                for packet in self._vstream.encode():
                    self._container.mux(packet)
            if self._astream is not None:
                target = int(end * AUDIO_RATE)
                self._next_audio_pts = self._encode_silence(
                    target - self._next_audio_pts, self._next_audio_pts)
                for packet in self._astream.encode():
                    self._container.mux(packet)
        except Exception as exc:
            self.error = self.error or f"写视频失败：{type(exc).__name__}: {exc}"
            self._stop.set()
        finally:
            try:
                if self._container is not None:
                    self._container.close()
            except Exception as exc:
                self.error = self.error or f"关闭视频失败：{type(exc).__name__}: {exc}"
            self._container = None

    def _drain_video(self) -> None:
        while True:
            try:
                pts, arr = self._vq.get_nowait()
            except queue.Empty:
                return
            if pts < self._next_video_pts:
                continue
            while self._next_video_pts <= pts:
                self._encode_video(arr, self._next_video_pts)
                self._next_video_pts += 1

    def _drain_audio(self) -> None:
        if self._astream is None:
            return
        while True:
            try:
                start, x, rate = self._aq.get_nowait()
            except queue.Empty:
                return
            target = int(start * AUDIO_RATE)
            if target > self._next_audio_pts:
                self._next_audio_pts = self._encode_silence(
                    target - self._next_audio_pts, self._next_audio_pts)
            self._next_audio_pts = self._encode_audio(
                x, rate, self._next_audio_pts)

    # ---- 转写给 ASR 的分块 ----

    def _push_asr(self, mono: np.ndarray, start: float, duration: float) -> None:
        if self.asr_chunks is None or mono.size == 0:
            return
        if self._asr_start is None:
            self._asr_start = start
        elif self._asr_expected is not None and start - self._asr_expected > 0.6:
            self._flush_asr()
            self._asr_start = start
        self._asr_buf.append(mono)
        self._asr_samples += int(mono.size)
        self._asr_expected = start + duration
        if self._asr_samples >= int(self.chunk_seconds * ASR_RATE):
            self._flush_asr()

    def _flush_asr(self) -> None:
        if self.asr_chunks is None or self._asr_start is None or not self._asr_buf:
            self._reset_asr()
            return
        if self._asr_samples >= int(MIN_ASR_SECONDS * ASR_RATE):
            samples = np.concatenate(self._asr_buf)
            stamp = self.started_at + datetime.timedelta(
                seconds=max(0.0, self._asr_start))
            try:
                self.asr_chunks.put_nowait((stamp, samples))
            except queue.Full:
                self.dropped += 1
        self._reset_asr()

    def _reset_asr(self) -> None:
        self._asr_buf = []
        self._asr_start = None
        self._asr_expected = None
        self._asr_samples = 0

    # ---- 幻灯片 / 缩略图 ----

    def _maybe_thumb(self, arr: np.ndarray) -> None:
        if self._thumb_done or self.thumb_path is None:
            return
        self._thumb_done = True
        try:
            from PIL import Image
            image = Image.fromarray(arr[:, :, ::-1])
            width = min(640, image.width)
            height = max(2, round(image.height * width / image.width))
            image.resize((width, height), Image.BILINEAR).save(
                self.thumb_path, "JPEG", quality=85)
        except Exception as exc:
            self._info(f"缩略图没存成：{type(exc).__name__}: {exc}")

    def _maybe_slide(self, arr: np.ndarray, at: float) -> None:
        if self.slides_dir is None or at < self._next_slide_check:
            return
        self._next_slide_check = at + self.slide_interval
        if len(self.slides) >= SLIDE_MAX:
            return
        try:
            from PIL import Image
            image = Image.fromarray(arr[:, :, ::-1])
            small = np.asarray(image.convert("L").resize((32, 32)), dtype=np.int16)
        except Exception:
            return
        if self._last_fp is not None:
            diff = float(np.abs(small - self._last_fp).mean())
            if diff < SLIDE_DIFF:
                return
        self._last_fp = small
        stamp = self.started_at + datetime.timedelta(seconds=max(0.0, at))
        name = f"slide_{len(self.slides) + 1:04d}_{stamp:%H%M%S}.jpg"
        path = self.slides_dir / name
        try:
            image.resize(
                (self._out_size[0], self._out_size[1]), Image.BILINEAR
            ).save(path, "JPEG", quality=85)
        except Exception as exc:
            self._info(f"幻灯片没存成：{type(exc).__name__}: {exc}")
            return
        self.slides.append(str(path))
        if self.on_slide is not None:
            try:
                self.on_slide(str(path), stamp.strftime("%Y-%m-%d %H:%M:%S"))
            except Exception:
                pass

    # ---- 杂项 ----

    def _info(self, text: str) -> None:
        if self.on_info is not None:
            try:
                self.on_info(str(text))
            except Exception:
                pass

    def _summary(self) -> dict:
        return {
            "录像路径": str(self.out_path),
            "开始时间": self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "录像秒数": self.duration,
            "录像字节": self.bytes,
            "画面帧数": self.frames,
            "丢帧数": self.dropped,
            "幻灯片张数": len(self.slides),
            "幻灯片目录": str(self.slides_dir or ""),
            "缩略图": str(self.thumb_path or ""),
            "声音": "有" if self.audio_ok else "无",
            "错误": self.error,
        }
