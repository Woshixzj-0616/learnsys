"""录像采集源：屏幕（mss）、系统声音（WASAPI loopback）、暂停时钟。

和 `video_recorder` 分开，是为了让「采集」和「编码/合流」各自可测、各自不过体量红线。
本文件不依赖 Qt，也不碰数据库。
"""
from __future__ import annotations

import threading
import time

import numpy as np

DEFAULT_MAX_WIDTH = 1600


class RecorderError(RuntimeError):
    """录像起不来（抓不到屏幕 / 声音设备打不开 / 编码器打不开）。"""


class Clock:
    """录像时间轴：暂停时冻结，恢复后从冻结点继续。"""

    def __init__(self) -> None:
        self._started = time.monotonic()
        self._paused_at = 0.0
        self._paused_total = 0.0
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            now = time.monotonic()
            value = now - self._started - self._paused_total
            if self._paused_at:
                value -= now - self._paused_at
            return max(0.0, value)

    def pause(self) -> None:
        with self._lock:
            if not self._paused_at:
                self._paused_at = time.monotonic()

    def resume(self) -> None:
        with self._lock:
            if self._paused_at:
                self._paused_total += time.monotonic() - self._paused_at
                self._paused_at = 0.0


def fit_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    """等比缩到最长边不超过 max_width；宽高都取偶数（yuv420p 要求）。"""
    width = max(2, int(width or 2))
    height = max(2, int(height or 2))
    if width > max_width:
        height = max(2, round(height * max_width / width))
        width = max_width
    width -= width % 2
    height -= height % 2
    return max(2, width), max(2, height)


class ScreenSource:
    """mss 抓主屏，返回 BGR ndarray。"""

    def __init__(self, max_width: int = DEFAULT_MAX_WIDTH) -> None:
        self.max_width = int(max_width)
        self._sct = None
        self._monitor = None
        self.size = (0, 0)
        self.error = ""

    def open(self) -> tuple[int, int]:
        try:
            import mss as mss_mod
            factory = getattr(mss_mod, "MSS", None) or mss_mod.mss
            self._sct = factory()
            self._monitor = self._sct.monitors[1]
        except Exception as exc:
            self.error = f"抓不到屏幕：{type(exc).__name__}: {exc}"
            raise RecorderError(self.error) from exc
        self.size = (int(self._monitor["width"]), int(self._monitor["height"]))
        return self.size

    def read(self) -> np.ndarray | None:
        try:
            shot = self._sct.grab(self._monitor)
        except Exception as exc:
            self.error = f"抓屏失败：{type(exc).__name__}: {exc}"
            return None
        arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
            shot.height, shot.width, 4)[:, :, :3]
        return np.ascontiguousarray(arr)

    def close(self) -> None:
        try:
            if self._sct is not None:
                self._sct.close()
        except Exception:
            pass
        self._sct = None


class LoopbackSource:
    """WASAPI 系统回环，返回原生采样率/声道的 float32 块。

    没有声音时 `read()` 会一直阻塞；`stop()` 从别的线程 `stop_stream()` 解锁。
    """

    def __init__(self, block_seconds: float = 0.2) -> None:
        self.block_seconds = max(0.05, float(block_seconds))
        self._pa = None
        self._stream = None
        self.rate = 0
        self.channels = 0
        self.level = 0.0
        self.error = ""
        self._closing = False

    def open(self) -> tuple[int, int]:
        try:
            import pyaudiowpatch as pa
            self._pa = pa.PyAudio()
            device = self._pa.get_default_wasapi_loopback()
            self.rate = int(device["defaultSampleRate"])
            self.channels = max(1, int(device["maxInputChannels"]))
            self._stream = self._pa.open(
                format=pa.paInt16, channels=self.channels, rate=self.rate,
                input=True, input_device_index=device["index"],
                frames_per_buffer=max(256, int(self.rate * self.block_seconds)))
        except Exception as exc:
            self.error = f"系统声音没起来：{type(exc).__name__}: {exc}"
            raise RecorderError(self.error) from exc
        return self.rate, self.channels

    def read(self) -> tuple[float, np.ndarray] | None:
        if self._stream is None:
            return None
        try:
            raw = self._stream.read(
                max(256, int(self.rate * self.block_seconds)),
                exception_on_overflow=False)
        except Exception as exc:
            if not self._closing:          # stop() 解锁 read() 时抛错是正常收尾
                self.error = f"读系统声音失败：{type(exc).__name__}: {exc}"
            return None
        now = time.monotonic()
        x = np.frombuffer(raw, dtype=np.int16).reshape(-1, self.channels)
        x = x.astype(np.float32) / 32768.0
        self.level = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
        return now, x

    def stop(self) -> None:
        """从别的线程调用：把阻塞中的 read() 解开。"""
        self._closing = True
        try:
            if self._stream is not None:
                self._stream.stop_stream()
        except Exception:
            pass

    def close(self) -> None:
        self._closing = True
        try:
            if self._stream is not None:
                self._stream.close()
        except Exception:
            pass
        try:
            if self._pa is not None:
                self._pa.terminate()
        except Exception:
            pass
        self._stream = None
        self._pa = None
