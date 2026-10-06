# -*- coding: utf-8 -*-
"""第三轮深审修复的回归测试（#24–#30）。

跑法：.venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtWidgets  # noqa: E402

from learnsys.ask import backend, bar, usage  # noqa: E402


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TestTrimHistoryEdge(unittest.TestCase):
    """#24 _trim_history 在 N=1 时 `[-0:]` 会取全表（Python 坑）。"""

    def test_n1_keeps_only_first(self):
        history = [(f"问{i}", f"答{i}") for i in range(6)]
        with mock.patch.object(backend.config, "ASK_HISTORY_TURNS", 1):
            trimmed = backend._trim_history(history)
        self.assertEqual(len(trimmed), 1)
        self.assertEqual(trimmed[0], ("问0", "答0"))

    def test_n2_keeps_first_and_last(self):
        history = [(f"问{i}", f"答{i}") for i in range(6)]
        with mock.patch.object(backend.config, "ASK_HISTORY_TURNS", 2):
            trimmed = backend._trim_history(history)
        self.assertEqual(trimmed[0], ("问0", "答0"))
        self.assertEqual(trimmed[-1], ("问5", "答5"))
        self.assertEqual(len(trimmed), 2)


class TestUsageSkipsBuildArtifacts(unittest.TestCase):
    """#25 打包产物 dist/build 不该算进「代码占的盘」。"""

    def test_skip_list_includes_dist_build(self):
        self.assertIn("dist", usage.SKIP)
        self.assertIn("build", usage.SKIP)


class TestEmptyQuestionAlwaysSpeaks(unittest.TestCase):
    """#26 有图时空问题也要给提示，不许静默。"""

    def test_empty_question_with_image_shows_message(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        b._image_path = "fake.png"        # 假装有图
        b.ask.setText("   ")
        b.submit()
        self.assertTrue(b.status.text().strip(), "空问题要有提示")
        self.assertIn("先打个问题", b.status.text())


class TestThinkingHeuristicNumbers(unittest.TestCase):
    """#27 带数字的短段落不许当思考铺垫删掉。"""

    def test_short_answer_with_number_kept(self):
        self.assertFalse(backend._looks_like_thinking("先看答案：42。"))

    def test_pure_lead_in_still_dropped(self):
        self.assertTrue(backend._looks_like_thinking("让我看看这张图。"))


class TestHistoryStatusHint(unittest.TestCase):
    """#28 看历史后复制，状态提示别变成「想问这块屏的什么」。"""

    def test_history_hint_after_copy(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        b._image_path = "fake.png"        # 有图
        b._show_past("历史问", "历史答", "text", "")
        b._restore_status_hint()
        self.assertIn("历史记录", b.status.text())


class TestPartialAnswerStaysInContext(unittest.TestCase):
    """#29 回答中断时已写出的那段要进上下文，追问「继续」才接得上。"""

    def test_partial_appended_to_turns(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        b._start_turn("问题")
        seq = b._turn_seq
        b._on_chunk("写到一半", replace=False, seq=seq)
        b._finish("问题", "", "断线了", seq, "text", "")
        self.assertEqual(b._turns, [("问题", "写到一半")],
                         "中断但有残文 ⇒ 该进上下文")


class TestWorkerReap(unittest.TestCase):
    """#30 跑完的 QThread 要销毁，不许在 bar 底下越积越多。"""

    def test_reap_calls_delete_later(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)

        class FakeWorker:
            def __init__(self, running):
                self._r = running
                self.deleted = False
            def isRunning(self):
                return self._r
            def deleteLater(self):
                self.deleted = True
            def cancel(self):
                pass
            def wait(self, _ms=0):
                return True

        done = FakeWorker(False)
        alive = FakeWorker(True)
        b._workers = [done, alive]
        b._reap_workers()
        self.assertTrue(done.deleted, "跑完的要 deleteLater")
        self.assertFalse(alive.deleted, "还在跑的要留着")
        self.assertEqual(b._workers, [alive])


if __name__ == "__main__":
    unittest.main(verbosity=2)
