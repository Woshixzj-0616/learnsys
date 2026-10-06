# -*- coding: utf-8 -*-
"""负责人真机反馈「清空/新会话后画面叠加」—— 三修，这次找到的是**真根因**。

一修（repaint）、二修（阴影缓存 + 分层窗口重合成）都在补像素层 —— 但离屏抓像素证明：
**清空后窗口根本没缩回去**。根因：`setVisible(False)` 只把直接父布局标脏 + 发异步
LayoutRequest，事件循环没转过之前，**外层布局的 sizeHint 和窗口最小尺寸都钉着旧值**，
`adjustSize()` 的 resize 被旧最小尺寸顶回去 —— 旧答案那一截高度就一直留在窗口里。

修法：`_relayout()`（invalidate + activate + adjustSize）当场重算。
本文件用真实尺寸断言把它锁死，不再是 mock 断言。
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtWidgets  # noqa: E402

from learnsys.ask import bar  # noqa: E402

LONG_ANSWER = "这是一段足够长的答案，能把答案区撑到七八十像素以上。" * 3


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class AskBarFixture(unittest.TestCase):
    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.b.show()
        QtWidgets.QApplication.processEvents()
        self._drain_usage()          # 占用统计是后台算的：不落定，usage_line 有没有字会晃 2px
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def _drain_usage(self) -> None:
        worker = self.b._usage_worker
        if worker is not None:
            worker.wait(10000)
            QtWidgets.QApplication.processEvents()

    def _fill(self, question: str = "第一问", answer: str = LONG_ANSWER) -> None:
        self.b._start_turn(question)
        seq = self.b._turn_seq
        self.b._on_chunk(answer, replace=False, seq=seq)
        self.b._finish(question, answer, None, seq, "text", "")
        QtWidgets.QApplication.processEvents()


class TestWindowActuallyShrinks(AskBarFixture):
    """清空 / 新会话之后，窗口高度必须**当场**缩回去（画面叠加的根子）。"""

    def test_clear_session_shrinks_window(self):
        self._fill()
        before = self.b.height()
        self.b.clear_session()
        QtWidgets.QApplication.processEvents()
        after = self.b.height()
        self.assertLess(after, before - 50,
                        f"清空后窗口没缩回去：{before} → {after}（旧答案那截还挂着）")

    def test_new_session_shrinks_window(self):
        self._fill()
        before = self.b.height()
        self.b.new_session()
        QtWidgets.QApplication.processEvents()
        after = self.b.height()
        self.assertLess(after, before - 50,
                        f"新会话后窗口没缩回去：{before} → {after}")

    def test_reset_answer_shrinks_window(self):
        self._fill()
        before = self.b.height()
        self.b._reset_answer()
        after = self.b.height()
        self.assertLess(after, before - 50,
                        f"_reset_answer 后窗口没缩回去：{before} → {after}")

    def test_width_stays_fixed_after_clear(self):
        self._fill()
        width = self.b.width()
        self.b.clear_session()
        QtWidgets.QApplication.processEvents()
        self.assertEqual(self.b.width(), width, "清空不该动宽度")

    def test_stays_shrunk_after_event_loop(self):
        """事件循环转过几圈之后也不许弹回去。"""
        self._fill()
        self.b.clear_session()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        shrunk = self.b.height()
        self._fill("第二问")
        self.b.clear_session()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        self.assertLessEqual(self.b.height(), shrunk + 2,
                             "再来一轮再清，高度不该越叠越高")

    def test_recording_line_toggles_height(self):
        """「记录中」那行显隐也要同步窗口尺寸（同一类残影）。

        先完整开/关一轮做热身 —— 记录行首次显示时 QSS 字号才落定（13→11），
        那之后量到的才是稳定尺寸，拿它当基准断言第二轮开/关对称。
        """
        self.b.set_recording(True, 1.0, 0)
        QtWidgets.QApplication.processEvents()
        self.b.set_recording(False)
        QtWidgets.QApplication.processEvents()
        base = self.b.height()
        self.b.set_recording(True, 1.0, 0)
        QtWidgets.QApplication.processEvents()
        self.assertGreater(self.b.height(), base, "出现记录行窗口该变高")
        self.b.set_recording(False)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(self.b.height(), base, "记录行收了窗口该缩回去")

    def test_collapse_stays_small(self):
        self._fill()
        self.b.set_collapsed(True)
        QtWidgets.QApplication.processEvents()
        self.assertLess(self.b.height(), 80, f"收起后窗口该是一条小条，现在是 {self.b.height()}")
        self.b.set_collapsed(False)
        QtWidgets.QApplication.processEvents()
        self.assertGreater(self.b.height(), 100, "展开后该回到完整横栏")


class TestLastAnswerResetsPerTurn(AskBarFixture):
    """_last_answer 是「当前这轮的答案」—— 每轮开头必须清零。

    不清的后果：① 流式期间点「复制」会把上一轮答案拼进来；
    ② 回答中断时 `_finish` 拿它当残文进上下文 —— 上一轮答案被拼第二遍。
    """

    def test_followup_turn_resets_last_answer(self):
        self._fill("第一问", "第一轮的答案")
        self.assertEqual(self.b._last_answer, "第一轮的答案")
        self.b._start_turn("第二问")          # 追问（不清文档的那种）
        self.assertEqual(self.b._last_answer, "", "新一轮开头上轮答案必须清掉")

    def test_chunk_after_new_turn_has_no_old_answer(self):
        self._fill("第一问", "第一轮的答案")
        self.b._start_turn("第二问")
        seq = self.b._turn_seq
        self.b._on_chunk("片段", replace=False, seq=seq)
        self.assertEqual(self.b._last_answer, "片段",
                         "流式片段不许接在上一轮答案后面")

    def test_interrupted_turn_context_not_polluted(self):
        self._fill("第一问", "第一轮的答案AAAA")
        self.b._start_turn("第二问")
        seq = self.b._turn_seq
        self.b._on_chunk("写到一半", replace=False, seq=seq)
        self.b._finish("第二问", "", "断线了", seq, "text", "")
        self.assertEqual(self.b._turns[-1], ("第二问", "写到一半"),
                         "中断进上下文的只能是这一轮的残文")
        self.assertEqual(self.b._turns[-1][1].count("第一轮的答案"), 0,
                         "上一轮答案被拼进残文了 —— 上下文被污染")

    def test_copy_during_stream_copies_current_only(self):
        self._fill("第一问", "第一轮的答案AAAA")
        self.b._start_turn("第二问")
        seq = self.b._turn_seq
        self.b._on_chunk("当前片段", replace=False, seq=seq)
        clipboard = QtWidgets.QApplication.clipboard()
        self.b._copy_answer()
        self.assertEqual(clipboard.text(), "当前片段")


class TestHistoryHintVisible(AskBarFixture):
    """看历史时那句「这是历史记录…」得真的显示出来（原来设了字但 status 藏着）。"""

    def test_show_past_shows_status_hint(self):
        self.b._show_past("历史问", "历史答", "text", "")
        self.assertTrue(self.b.status.isVisible())
        self.assertIn("历史记录", self.b.status.text())


class TestUsageWorkerReaped(AskBarFixture):
    """占用统计线程用完要摘引用 + 销毁，不然 refresh_usage 会摸到已销毁的对象。"""

    def test_reference_cleared_after_finish(self):
        self.b._usage_cache = None   # setUp 里已经算过一次（缓存住了）—— 清掉才真的会起线程
        self.b._usage_at = 0.0
        self.b.refresh_usage()
        worker = self.b._usage_worker
        self.assertIsNotNone(worker)
        self.assertTrue(worker.wait(10000))
        QtWidgets.QApplication.processEvents()   # finished 是队列信号，转一圈才落地
        self.assertIsNone(self.b._usage_worker, "跑完该把引用摘掉")


if __name__ == "__main__":
    unittest.main(verbosity=2)
