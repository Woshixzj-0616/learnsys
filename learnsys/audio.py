"""系统声音回环采集：WASAPI loopback → 16kHz 单声道 float32。

抓的是**系统输出**（戴耳机也能抓），不是麦克风。
只往上游交「音频块」；原始音频不落盘（转写完的文本才进库）。
"""
from __future__ import annotations

import datetime as dt
import queue
import threading

import numpy as np

TARGET_RATE = 16000
BLOCK_SECONDS = 0.5


def to_mono_16k(block: np.ndarray, rate: int) -> np.ndarray:
    """任意采样率 / 声道数 → 16kHz 单声道 float32。"""
    x = block.astype(np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if rate == TARGET_RATE:
        return x
    if rate % TARGET_RATE == 0:
        # 48000 → 16000：每 3 个取均值（顺带当低通，够用）
        k = rate // TARGET_RATE
        n = (x.size // k) * k
        return x[:n].reshape(-1, k).mean(axis=1)
    n_new = int(x.size * TARGET_RATE / rate)
    return np.interp(np.arange(n_new) / TARGET_RATE, np.arange(x.size) / rate, x).astype(np.float32)


class LoopbackRecorder:
    """后台线程：持续读系统输出，每 chunk_seconds 秒交一块 (开始时刻, samples) 给下游。

    结束时往 chunks 里塞一个 None 当哨兵，下游看到就收工。
    """

    def __init__(self, chunks: queue.Queue, chunk_seconds: float = 25.0):
        self.chunks = chunks
        self.chunk_seconds = chunk_seconds
        self.level = 0.0        # 最近一块的响度（UI 用来看「有没有在听」）
        self.device = ""
        self.error = ""
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="audio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            import pyaudiowpatch as pa
        except Exception as exc:
            self.error = f"没有 pyaudiowpatch（{type(exc).__name__}: {exc}），声音这一路没启动"
            self.chunks.put(None)
            return
        p = pa.PyAudio()
        stream = None
        try:
            spk = p.get_default_wasapi_loopback()
            rate = int(spk["defaultSampleRate"])
            channels = max(1, int(spk["maxInputChannels"]))
            self.device = f"{spk['name']} @ {rate}Hz x{channels}"
            block_frames = int(rate * BLOCK_SECONDS)
            stream = p.open(format=pa.paInt16, channels=channels, rate=rate, input=True,
                            input_device_index=spk["index"], frames_per_buffer=block_frames)
            need = int(rate * self.chunk_seconds)
            buf: list[np.ndarray] = []
            frames = 0
            started = dt.datetime.now()
            while not self._stop.is_set():
                raw = stream.read(block_frames, exception_on_overflow=False)
                block = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                if channels > 1:
                    block = block.reshape(-1, channels)
                self.level = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
                buf.append(block)
                frames += int(block.shape[0])
                if frames >= need:
                    self.chunks.put((started, to_mono_16k(np.concatenate(buf), rate)))
                    started = dt.datetime.now()
                    buf, frames = [], 0
            if buf:
                self.chunks.put((started, to_mono_16k(np.concatenate(buf), rate)))
        except Exception as exc:
            self.error = f"打开系统回环失败：{type(exc).__name__}: {exc}"
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            finally:
                try:
                    p.terminate()
                finally:
                    self.chunks.put(None)

def active_players(min_peak: float = 0.005, exclude: tuple = ("python.exe", "pythonw.exe")) -> list:
    """现在有哪些程序在往扬声器送声音 → [(名字, 峰值)]。

    回环采的是**整个系统的声音**，所以游戏 / 音乐一起被录进去，转写就会一团糟。
    没装 pycaw 就返回空表（不影响录音）。"""
    try:
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    except Exception:
        return []
    out = []
    try:
        for s in AudioUtilities.GetAllSessions():
            try:
                name = s.Process.name() if s.Process else ""
                if not name or name.lower() in exclude:
                    continue
                peak = float(s._ctl.QueryInterface(IAudioMeterInformation).GetPeakValue())
            except Exception:
                continue
            if peak >= min_peak:
                out.append((name, round(peak, 3)))
    except Exception:
        return []
    return out
