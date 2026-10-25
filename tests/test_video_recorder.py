# -*- coding: utf-8 -*-
"""录像引擎：用注入的屏幕/声音源跑通 MP4、暂停时间轴、幻灯片与无声音兜底。"""
from __future__ import annotations

import pathlib
import queue
import tempfile
import threading
import time
import unittest

import numpy as np

from learnsys.services.video_recorder import (
    Clock,
    RecorderError,
    VideoRecorder,
    fit_size,
)


class FakeScreen:
    def __init__(self, frames, size=(320, 240)):
        self.frames = frames
        self.size = size
        self.index = 0
        self.closed = False

    def open(self):
        return self.size

    def read(self):
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return frame

    def close(self):
        self.closed = True


class FakeAudio:
    def __init__(self, rate=16000, channels=1, fail=False):
        self.rate = rate
        self.channels = channels
        self.level = 0.01
        self.fail = fail
        self._stop = threading.Event()
        self.blocks = 0

    def open(self):
        if self.fail:
            raise RecorderError("没有声音设备")
        return self.rate, self.channels

    def read(self):
        if self._stop.is_set():
            return None
        time.sleep(0.03)
        self.blocks += 1
        n = int(self.rate * 0.03)
        t = np.arange(n, dtype=np.float32) / self.rate
        wave = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        if self.channels == 1:
            block = wave[:, None]
        else:
            block = np.repeat(wave[:, None], self.channels, axis=1)
        return time.monotonic(), block

    def stop(self):
        self._stop.set()

    def close(self):
        self._stop.set()


def _frames(count=30):
    return [np.full((240, 320, 3), (i * 12) % 255, dtype=np.uint8)
            for i in range(count)]


def _record(root, *, audio=None, pause=0.0, seconds=0.5, slide_interval=0.1):
    chunks: queue.Queue = queue.Queue()
    recorder = VideoRecorder(
        out_path=root / "video.mp4",
        fps=10,
        max_width=320,
        chunk_seconds=0.1,
        slides_dir=root / "slides",
        thumb_path=root / "thumb.jpg",
        asr_chunks=chunks,
        screen_source=FakeScreen(_frames()),
        audio_source=audio or FakeAudio(),
        slide_interval=slide_interval,
    )
    recorder.start()
    time.sleep(seconds)
    if pause:
        recorder.pause()
        time.sleep(pause)
        recorder.resume()
        time.sleep(seconds)
    summary = recorder.stop()
    return recorder, summary, chunks


class VideoRecorderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fit_size_keeps_aspect_and_even(self):
        self.assertEqual(fit_size(2560, 1600, 1600), (1600, 1000))
        self.assertEqual(fit_size(1920, 1080, 2560), (1920, 1080))
        self.assertEqual(fit_size(1001, 999, 800), (800, 798))

    def test_clock_pauses_without_advancing(self):
        clock = Clock()
        time.sleep(0.08)
        before = clock.now()
        clock.pause()
        time.sleep(0.2)
        during = clock.now()
        self.assertLess(abs(during - before), 0.05)
        clock.resume()
        time.sleep(0.1)
        self.assertGreaterEqual(clock.now() - during, 0.08)

    def test_records_mp4_with_two_streams(self):
        _recorder, summary, chunks = _record(self.root)
        path = self.root / "video.mp4"
        self.assertTrue(path.exists() and path.stat().st_size > 0)
        self.assertEqual(summary["声音"], "有")
        self.assertGreaterEqual(summary["录像秒数"], 0.3)
        self.assertGreater(summary["画面帧数"], 0)

        import av
        container = av.open(str(path))
        kinds = {stream.type for stream in container.streams}
        container.close()
        self.assertEqual(kinds, {"video", "audio"})

        self.assertTrue((self.root / "thumb.jpg").exists())
        slides = list((self.root / "slides").glob("*.jpg"))
        self.assertTrue(slides, "画面在变，应该存下幻灯片")
        items = []
        while not chunks.empty():
            items.append(chunks.get())
        self.assertTrue(items and items[-1] is None)

    def test_pause_removes_dead_time(self):
        _recorder, summary, _chunks = _record(
            self.root, seconds=0.35, pause=0.4)
        self.assertGreaterEqual(summary["录像秒数"], 0.5)
        self.assertLessEqual(summary["录像秒数"], 0.9)

    def test_missing_audio_still_records_video(self):
        _recorder, summary, _chunks = _record(
            self.root, audio=FakeAudio(fail=True), seconds=0.3)
        self.assertEqual(summary["声音"], "无")
        self.assertGreater((self.root / "video.mp4").stat().st_size, 0)
        import av
        container = av.open(str(self.root / "video.mp4"))
        kinds = {stream.type for stream in container.streams}
        container.close()
        self.assertEqual(kinds, {"video"})


if __name__ == "__main__":
    unittest.main()
