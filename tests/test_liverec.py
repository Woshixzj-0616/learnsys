# -*- coding: utf-8 -*-
"""「录制」三路编排的回归测试（音频/转写全 fake，快照指向临时目录，不碰真麦克风）。

覆盖：会话开合、转写落库、快照计数、汇总信号、横栏录制按钮与状态行。
"""
from __future__ import annotations

import os
import queue
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PySide6 import QtGui, QtWidgets  # noqa: E402

from learnsys import store  # noqa: E402
from learnsys.ask import bar, liverec  # noqa: E402


def _app():
    a = QtWidgets.QApplication.instance()
    if a is None:
        a = QtWidgets.QApplication([])
    return a


class FakeTranscriber:
    """替身转写器：load 永远成功，转写返回固定一句话。"""

    def __init__(self):
        self.load_error = ""
        self.calls = 0

    def load(self):
        return True

    def transcribe(self, samples):
        self.calls += 1
        return [(0.0, 1.0, "老师讲到单链表插入")]


class FakeLoopback:
    """替身回环采集：start 时塞两块「有声音」的数据，stop 时塞哨兵。"""

    level = 0.0
    device = "fake"
    error = ""
    instances = []

    def __init__(self, chunks: queue.Queue, chunk_seconds: float = 25.0):
        self.chunks = chunks
        self.chunk_seconds = chunk_seconds
        self._stop = None
        FakeLoopback.instances.append(self)

    def start(self):
        self._stop = object()
        speaking = np.full(16000 * 3, 0.1, dtype=np.float32)   # RMS 0.1 > 静音线
        self.chunks.put((__import__("datetime").datetime.now(), speaking))

    def stop(self):
        self.chunks.put(None)


class TestLiveRecorder(unittest.TestCase):
    """三路编排：开 → 转写落库 → 停 → 汇总。"""

    def setUp(self):
        _app()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.rec = liverec.LiveRecorder(lambda: self.conn)
        fake_tr = FakeTranscriber()
        self.fake_tr = fake_tr
        fake_img = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_ARGB32)
        fake_img.fill(0)
        patchers = [
            mock.patch.object(liverec, "_get_transcriber", return_value=fake_tr),
            mock.patch.object(liverec.audio, "LoopbackRecorder", FakeLoopback),
            mock.patch.object(liverec, "grab_all_screens_image", return_value=fake_img),
            mock.patch.object(liverec, "frame_dir",
                              return_value=__import__("pathlib").Path(self.tmp.name) / "录屏"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

        self.addCleanup(self.rec.stop)   # 放在补丁之后注册：LIFO ⇒ stop 先于补丁卸载执行
        self.stopped = []
        self.rec.stopped.connect(lambda s: self.stopped.append(s))

    def _wait_stopped(self, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline and not self.stopped:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.02)
        return self.stopped[0] if self.stopped else {}

    def test_start_stop_records_transcript_and_frames(self):
        self.assertFalse(self.rec.recording)
        self.rec.start()
        self.assertTrue(self.rec.recording)
        self.rec.stop()                          # 触发收尾（后台线程）
        summary = self._wait_stopped()
        self.rec.stop()                          # 幂等：收尾中再停不许崩
        self.assertEqual(summary.get("转写字数"), len("老师讲到单链表插入"))
        self.assertGreaterEqual(summary.get("快照张数", 0), 1, "开录那一刻就该有一张快照")
        rows = store.search_transcripts(self.conn)
        self.assertTrue(any("单链表插入" in (r[3] or "") for r in rows), "转写要落库")
        # 会话开合：sessions 表里有一条且已结束
        sess = self.conn.execute("SELECT started_at, ended_at FROM sessions").fetchall()
        self.assertEqual(len(sess), 1)
        self.assertTrue(sess[0][1], "结束时要 end_session")

    def test_recording_flag_blocks_double_start(self):
        self.rec.start()
        self.assertTrue(self.rec.recording)
        FakeLoopback.instances.clear()
        self.rec.start()                         # 录制中再点 = 忽略
        self.assertEqual(len(FakeLoopback.instances), 0, "录制中不许再起第二路采集")
        self.rec.stop()
        self._wait_stopped()

    def test_frame_saved_to_tmp_dir(self):
        self.rec.start()
        self.rec._grab_frame()                   # 手动触发一张
        self.rec.stop()
        self._wait_stopped()
        import pathlib
        frames = list(pathlib.Path(self.tmp.name).rglob("frame_*.jpg"))
        self.assertGreaterEqual(len(frames), 2, "开录一张 + 手动一张")


class TestBarRecButton(unittest.TestCase):
    """横栏「录制」按钮：信号、状态字、红字提醒。"""

    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def test_click_emits_record_toggled(self):
        got = []
        self.b.record_toggled.connect(lambda: got.append(1))
        self.b.rec_btn.click()
        self.assertEqual(got, [1])

    def test_set_recording_updates_button_and_line(self):
        self.assertEqual(self.b.rec_btn.text(), "录制")
        self.b.set_recording(True, 2.0, 3, "转写 45 字 · 快照 2 张")
        self.assertEqual(self.b.rec_btn.text(), "停止录制")
        self.assertIn("录制中 2 分", self.b.rec_line.text())
        self.assertIn("转写 45 字", self.b.rec_line.text())
        self.assertIn("快照 2 张", self.b.rec_line.text())
        self.b.set_recording(False)
        self.assertEqual(self.b.rec_btn.text(), "录制")
        self.assertFalse(self.b.rec_line.isVisible())


if __name__ == "__main__":
    unittest.main(verbosity=2)
