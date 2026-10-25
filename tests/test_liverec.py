# -*- coding: utf-8 -*-
"""「录像」一次会话的编排回归：会话开合、转写落库、汇总、按钮状态。

视频引擎本身在 `test_video_recorder.py` 用假屏幕/假声卡测；这里把
`VideoRecorder` 整个换成替身，只测 LiveRecorder 的接线。
"""
from __future__ import annotations

import datetime
import os
import pathlib
import queue
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PySide6 import QtCore, QtWidgets  # noqa: E402

from learnsys import store  # noqa: E402
from learnsys.ask import bar, liverec  # noqa: E402
from learnsys.ask.desktop.sessions import SessionsMixin, _human_size  # noqa: E402


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class FakeTranscriber:
    def __init__(self):
        self.load_error = ""
        self.calls = 0

    def load(self):
        return True

    def transcribe(self, samples):
        self.calls += 1
        return [(0.0, 1.0, "老师讲到单链表插入")]


class FakeVideoRecorder:
    """替身录像引擎：start 塞一块「有声音」的音频，stop 塞哨兵并给汇总。"""

    instances: list["FakeVideoRecorder"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.asr_chunks: queue.Queue = kwargs["asr_chunks"]
        self.out_path = kwargs["out_path"]
        self.slides_dir = kwargs.get("slides_dir")
        self.started_at = datetime.datetime(2026, 10, 25, 14, 3, 0)
        self.slides: list[str] = []
        self.duration = 0.0
        self.bytes = 0
        self.level = 0.1
        self.running = False
        FakeVideoRecorder.instances.append(self)

    def start(self):
        self.running = True
        speaking = np.full(16000 * 3, 0.1, dtype=np.float32)
        self.asr_chunks.put((self.started_at, speaking))

    def stop(self):
        self.running = False
        self.asr_chunks.put(None)
        self.duration = 3.0
        self.bytes = 1234
        return {
            "录像路径": str(self.out_path),
            "开始时间": self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "录像秒数": 3.0,
            "录像字节": 1234,
            "画面帧数": 30,
            "丢帧数": 0,
            "幻灯片张数": 0,
            "幻灯片目录": str(self.slides_dir or ""),
            "缩略图": "",
            "声音": "有",
            "错误": "",
        }

    def pause(self):
        self.running = False

    def resume(self):
        self.running = True

    @property
    def listening(self):
        return True


class TestLiveRecorder(unittest.TestCase):
    def setUp(self):
        _app()
        FakeVideoRecorder.instances = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.rec = liverec.LiveRecorder(lambda: self.conn)
        self.fake_tr = FakeTranscriber()
        patchers = [
            mock.patch.object(liverec, "_get_transcriber", return_value=self.fake_tr),
            mock.patch.object(liverec, "VideoRecorder", FakeVideoRecorder),
            mock.patch.object(liverec.config, "VIDEO_DIR",
                              pathlib.Path(self.tmp.name) / "录像"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.rec.stop)
        self.stopped = []
        self.rec.stopped.connect(lambda s: self.stopped.append(s))

    def _wait_stopped(self, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline and not self.stopped:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.02)
        return self.stopped[0] if self.stopped else {}

    def test_start_stop_records_transcript_and_video_row(self):
        self.assertFalse(self.rec.recording)
        self.rec.start()
        self.assertTrue(self.rec.recording)
        self.rec.stop()
        summary = self._wait_stopped()
        self.rec.stop()                          # 幂等：收尾中再停不许崩
        self.assertEqual(summary.get("转写字数"), len("老师讲到单链表插入"))
        self.assertEqual(summary.get("录像秒数"), 3.0)
        self.assertGreaterEqual(summary.get("录像字节", 0), 1)
        rows = store.search_transcripts(self.conn)
        self.assertTrue(any("单链表插入" in (r[3] or "") for r in rows), "转写要落库")
        sess = self.conn.execute(
            "SELECT ended_at, video_path, duration_ms FROM sessions").fetchall()
        self.assertEqual(len(sess), 1)
        self.assertTrue(sess[0][0], "结束时要 end_session")
        self.assertTrue(sess[0][1].endswith("video.mp4"), "录像路径要写进库")
        self.assertEqual(sess[0][2], 3000)

    def test_recording_flag_blocks_double_start(self):
        self.rec.start()
        self.assertTrue(self.rec.recording)
        self.rec.start()                         # 录像中再点 = 忽略
        self.assertEqual(len(FakeVideoRecorder.instances), 1,
                         "录像中不许再起第二个引擎")
        self.rec.stop()
        self._wait_stopped()

    def test_slide_callback_forwards_session_id(self):
        got = []
        self.rec.slide_saved = lambda path, ts, sid: got.append((path, ts, sid))
        self.rec._slide_session_id = 7
        self.rec._on_slide("a.jpg", "2026-10-25 14:03:09")
        self.assertEqual(got, [("a.jpg", "2026-10-25 14:03:09", 7)])

    def test_start_failure_does_not_leave_recording(self):
        class Broken(FakeVideoRecorder):
            def start(self):
                raise RuntimeError("抓不到屏幕")

        with mock.patch.object(liverec, "VideoRecorder", Broken):
            self.rec.start()
        self.assertFalse(self.rec.recording)
        ended = self.conn.execute(
            "SELECT ended_at FROM sessions").fetchall()
        self.assertEqual(len(ended), 1)
        self.assertTrue(ended[0][0], "起不来也要把会话收尾")



class TestBarRecButton(unittest.TestCase):
    """横栏「录像」按钮：信号、状态字、红字提醒。"""

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
        self.assertEqual(self.b.rec_btn.text(), "录像")
        self.b.set_recording(True, 2.0, 3, "转写 45 字 · 幻灯片 2 张")
        self.assertEqual(self.b.rec_btn.text(), "停止")
        self.assertIn("录像中 02:00", self.b.rec_line.text())
        self.assertIn("转写 45 字", self.b._rec_text)
        self.assertIn("幻灯片 2 张", self.b._rec_text)
        self.b.set_recording(False)
        self.assertEqual(self.b.rec_btn.text(), "录像")
        self.assertEqual(self.b.rec_line.text(), "")

    def test_pending_button_can_cancel(self):
        self.b.set_record_pending(3)
        self.assertEqual(self.b.rec_btn.text(), "取消 3")
        self.b.set_record_pending(0)
        self.assertEqual(self.b.rec_btn.text(), "录像")

    def test_recording_result_card_and_link(self):
        got = []
        self.b.open_link_requested.connect(got.append)
        self.b.show_recording_result("【录像完成】5 分钟 · 96.4 MB", 12)
        self.assertEqual(self.b._state_name, "done")
        self.assertIn("录像完成", self.b.answer.toPlainText())
        self.assertIn("打开录像页", self.b.answer.toPlainText())
        self.b._on_answer_anchor(QtCore.QUrl("#/recordings?session=12"))
        self.assertEqual(got, ["#/recordings?session=12"])


class _FakeBar:
    def __init__(self):
        self.messages = []
        self.pending = []
        self.hidden = False
        self.excluded = False

    def show_message(self, text):
        self.messages.append(text)

    def set_record_pending(self, left=0):
        self.pending.append(left)

    def hide_bar(self):
        self.hidden = True

    def set_capture_excluded(self, excluded):
        self.excluded = bool(excluded)
        return True


class _FakeTray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *args):
        self.messages.append(args)


class _FakeHotkey:
    pretty = "Ctrl+Alt+S"
    registered = True


class _FakeLive:
    def __init__(self):
        self.recording = False
        self.finishing = False
        self.duration = 0.0
        self.bytes = 0
        self.chars = 0
        self.session_id = 0
        self.started = 0
        self.stopped = 0

    def start(self):
        self.recording = True
        self.started += 1

    def stop(self):
        self.recording = False
        self.stopped += 1


class _FakeApp(SessionsMixin, QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.bar = _FakeBar()
        self.tray = _FakeTray()
        self.stop_hotkey = _FakeHotkey()
        self.live = _FakeLive()
        self.warned = []
        self.opened = []
        self._web_port = 0

    def _open_workbench_link(self, href):
        self.opened.append(href)

    def _warn(self, text):
        self.warned.append(text)

    def show_bar(self):
        self.bar.hidden = False


class CountdownTest(unittest.TestCase):
    def setUp(self):
        _app()
        self.app = _FakeApp()
        self.addCleanup(self.app._cancel_record_start)

    def test_countdown_then_start_with_bar_visible(self):
        self.app._toggle_record()
        self.assertEqual(self.app._record_left, 3)
        self.assertEqual(self.app.bar.pending[0], 3)
        for _ in range(3):
            self.app._record_countdown_tick()
        self.assertEqual(self.app._record_left, 0)
        self.assertTrue(self.app.live.recording)
        self.assertFalse(self.app.bar.hidden, "横栏不藏，用户要随时点停止")
        self.assertTrue(self.app.bar.excluded, "横栏要从屏幕捕获里排除")
        self.assertIn("Ctrl+Alt+S", self.app.tray.messages[-1][1])

    def test_second_click_cancels_countdown(self):
        self.app._toggle_record()
        self.app._toggle_record()
        self.assertEqual(self.app._record_left, 0)
        self.assertFalse(self.app.live.recording)
        self.assertEqual(self.app.bar.pending[-1], 0)
        self.assertIn("已取消录像", self.app.bar.messages[-1])

    def test_hotkey_stops_running_recording(self):
        self.app.live.recording = True
        self.app._stop_record_hotkey()
        self.assertFalse(self.app.live.recording)
        self.assertEqual(self.app.live.stopped, 1)


    def test_saved_opens_recordings_page(self):
        self.app._live_saved({"会话": 9, "录像秒数": 3.0, "录像字节": 1234})
        self.assertEqual(self.app.opened, ["#/recordings?session=9"])
        self.assertFalse(self.app.bar.excluded)
        self.assertIn("录像已保存", self.app.bar.messages[-1])

    def test_record_state_exposes_progress(self):
        self.app.live.recording = True
        self.app.live.duration = 65.5
        self.app.live.bytes = 2048
        self.app.live.chars = 12
        self.app.live.session_id = 7
        self.app._record_left = 0
        state = self.app._record_state()
        self.assertTrue(state["recording"])
        self.assertFalse(state["finishing"])
        self.assertEqual(state["duration"], 65.5)
        self.assertEqual(state["session_id"], 7)

    def test_summary_mentions_size_and_folder(self):
        text = self.app._record_summary({
            "录像秒数": 125.0, "录像字节": 100 * 1024 * 1024,
            "转写字数": 812, "转写条数": 9, "幻灯片张数": 3,
            "录像目录": r"D:\学习系统\录像\20261025-140300-1",
            "最久": ("Code.exe", 30.0),
        })
        self.assertIn("100.0 MB", text)
        self.assertIn("转写 812 字", text)
        self.assertIn("幻灯片 3 张", text)
        self.assertIn("20261025-140300-1", text)
        self.assertEqual(_human_size(1024 * 1024), "1.0 MB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
