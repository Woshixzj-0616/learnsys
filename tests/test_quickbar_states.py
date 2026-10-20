# -*- coding: utf-8 -*-
"""快捷栏状态机（T3.5）回归测试。

锁三件事：
① **几何只由状态和面板高度决定** —— 流式、状态文字、录制行都不许让窗口跳；
② 状态显隐只有一个入口 `set_state()`，清空/新会话当场缩回紧凑几何、无残影；
③ 框选不隐藏横栏，靠遮罩上的不透明块把它盖住（截图抓不到、焦点不丢）。

旧的 test_clear_residue*.py 测的是「事后补丁」（_relayout / _force_repaint）——
几何稳定后补丁删除，那些断言一并收进这里的新口径。
"""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtWidgets  # noqa: E402

from learnsys.ask import bar, overlay  # noqa: E402

LONG_ANSWER = "这是一段足够长的答案，能把答案区撑出内部滚动条。" * 30


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
        self._drain_usage()
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


class TestFixedGeometry(AskBarFixture):
    """窗口高度：紧凑 → 展开只发生一次；流式/状态文字/录制行不再改高度。"""

    def test_idle_is_compact(self):
        self.assertFalse(self.b.answer.isVisible())
        self.assertEqual(self.b.height(), self.b._compact_card_h() + bar.BAR_OUTER_TOP)

    def test_ask_expands_once_then_streaming_keeps_height(self):
        self.b._start_turn("问题")
        thinking_h = self.b.height()
        self.assertEqual(thinking_h, self.b._expanded_card_h() + bar.BAR_OUTER_TOP)
        seq = self.b._turn_seq
        for _ in range(20):
            self.b._on_chunk(LONG_ANSWER, replace=False, seq=seq)
            self.assertEqual(self.b.height(), thinking_h,
                             "流式追加内容不许改变窗口高度")
        self.b._finish("问题", LONG_ANSWER, None, seq, "text", "")
        self.assertEqual(self.b.height(), thinking_h,
                         "thinking → streaming → done 高度必须完全一致")

    def test_answer_panel_stays_fixed_and_scrolls(self):
        self._fill()
        self.assertEqual(self.b.answer.height(), self.b._answer_h)
        self.assertGreater(self.b.answer.verticalScrollBar().maximum(), 0,
                           "内容超长时应内部滚动，而不是把窗口撑高")

    def test_clear_and_new_session_shrink_once(self):
        self._fill()
        tall = self.b.height()
        self.b.clear_session()
        QtWidgets.QApplication.processEvents()
        self.assertLess(self.b.height(), tall - 50,
                        f"清空后窗口没缩回去：{tall} → {self.b.height()}")
        self.assertEqual(self.b.height(), self.b._compact_card_h() + bar.BAR_OUTER_TOP)
        self.assertTrue(self.b.answer.isHidden())
        # 再来一轮再清，不许越叠越高
        self._fill("第二问")
        self.b.new_session()
        QtWidgets.QApplication.processEvents()
        self.assertEqual(self.b.height(), self.b._compact_card_h() + bar.BAR_OUTER_TOP)
        self.assertTrue(self.b.answer.isHidden())

    def test_width_never_changes_with_states(self):
        width = self.b.width()
        self._fill()
        self.assertEqual(self.b.width(), width)
        self.b.clear_session()
        self.assertEqual(self.b.width(), width)

    def test_recording_line_does_not_change_height(self):
        base = self.b.height()
        self.b.set_recording(True, 3.0, 4, "转写 45 字 · 快照 2 张")
        QtWidgets.QApplication.processEvents()
        self.assertEqual(self.b.height(), base, "录制行常驻固定高度，开关录制不许推窗口")
        self.assertIn("录制中", self.b.rec_line.text())
        self.b.set_recording(False)
        self.assertEqual(self.b.height(), base)
        self.assertEqual(self.b.rec_line.text(), "")

    def test_long_status_message_does_not_change_height(self):
        base = self.b.height()
        self.b.show_message("很长的一句状态提示" * 20)
        self.assertEqual(self.b.height(), base, "状态行固定一行高，长文只截断")
        self.assertEqual(self.b.status.height(), bar.STATUS_H)
        self.assertTrue(self.b.status.toolTip(), "被截断时悬停要能看全文")

    def test_collapse_and_expand(self):
        self._fill()
        expanded = self.b.height()
        self.b.set_collapsed(True)
        QtWidgets.QApplication.processEvents()
        self.assertLess(self.b.height(), 80)
        self.b.set_collapsed(False)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(self.b.height(), expanded, "展开回来还是固定的展开高度")

    def test_answer_drag_changes_height_by_delta(self):
        self._fill()
        before_h = self.b.height()
        before_answer = self.b._answer_h
        delta = min(40, self.b._answer_cap - before_answer)
        if delta <= 0:                      # 屏幕太矮时先缩一点，保证有可拖空间
            self.b._resize_answer(-40)
            self.b._finish_resize()
            before_answer = self.b._answer_h
            before_h = self.b.height()
            delta = 40
        self.b._resize_answer(delta)
        self.assertEqual(self.b._answer_h, before_answer + delta)
        self.assertEqual(self.b.height(), before_h + delta)
        self.b._finish_resize()
        # 往下拖过头 / 往上拖过头都被夹住
        self.b._resize_answer(10_000)
        self.assertEqual(self.b._answer_h, self.b._answer_cap)
        self.b._finish_resize()
        self.b._resize_answer(-10_000)
        self.assertEqual(self.b._answer_h, min(bar.config.ASK_BAR_ANSWER_MIN_H, self.b._answer_cap))

    def test_patch_methods_are_gone(self):
        """事后补丁已删除：几何稳定后不再需要强制重画 / adjustSize 抢救。"""
        for name in ("_force_repaint", "_relayout", "_fit_answer", "_schedule_fit"):
            self.assertFalse(hasattr(self.b, name), f"{name} 应该已经删除")

    def test_reset_does_not_touch_window_opacity(self):
        self._fill()
        calls = []
        with mock.patch.object(self.b, "setWindowOpacity",
                               side_effect=lambda v: calls.append(v)):
            self.b._reset_answer()
        self.assertEqual(calls, [], "清空不许再抖透明度（那正是要删掉的抖动）")


class TestStateMachine(AskBarFixture):
    """显隐/启用只有一个入口：set_state()。"""

    def test_unknown_state_rejected(self):
        with self.assertRaises(ValueError):
            self.b.set_state("not-a-state")

    def test_answer_visibility_follows_state(self):
        for state in (bar.STATE_THINKING, bar.STATE_STREAMING, bar.STATE_DONE,
                      bar.STATE_ERROR, bar.STATE_HISTORY):
            self.b.set_state(state)
            self.assertTrue(self.b._answer_shown, f"{state} 应显示答案面板")
        self.b.set_state(bar.STATE_IDLE)
        self.assertFalse(self.b._answer_shown)

    def test_buttons_follow_state(self):
        self.b.set_state(bar.STATE_THINKING)
        self.assertFalse(self.b.go.isEnabled(), "思考中不许再提交")
        self.b.set_state(bar.STATE_STREAMING)
        self.assertFalse(self.b.go.isEnabled())
        self.b.set_state(bar.STATE_DONE)
        self.assertTrue(self.b.go.isEnabled())
        self.assertFalse(self.b.copy_btn.isEnabled(), "没有答案时复制仍占位但不可点")

    def test_star_only_in_done_or_history(self):
        self.b.set_starrable("D:/x/learnsys.db", 7)
        self.b.set_state(bar.STATE_IDLE)
        self.assertFalse(self.b.star_btn.isEnabled())
        self.b.set_state(bar.STATE_THINKING)
        self.assertFalse(self.b.star_btn.isEnabled())
        self.b.set_state(bar.STATE_DONE)
        self.assertTrue(self.b.star_btn.isEnabled())
        self.b.set_state(bar.STATE_HISTORY)
        self.assertTrue(self.b.star_btn.isEnabled())

    def test_thinking_to_streaming_does_not_move_window(self):
        self.b._start_turn("问题")
        height = self.b.height()
        self.b._on_chunk("第一片", replace=False, seq=self.b._turn_seq)
        self.assertEqual(self.b.height(), height)


class TestAnswerContent(AskBarFixture):
    """原有内容层回归：清空干净、每轮 _last_answer 不串、历史提示可见。"""

    def test_clear_wipes_text_and_hides_panel(self):
        self._fill("问", "答案内容")
        self.b.clear_session()
        self.assertEqual(self.b.answer.toPlainText(), "")
        self.assertTrue(self.b.answer.isHidden())

    def test_new_session_wipes_answer(self):
        self._fill("问", "答案内容")
        self.b.new_session()
        self.assertEqual(self.b.answer.toPlainText(), "")
        self.assertTrue(self.b.answer.isHidden())

    def test_followup_turn_resets_last_answer(self):
        self._fill("第一问", "第一轮的答案")
        self.assertEqual(self.b._last_answer, "第一轮的答案")
        self.b._start_turn("第二问")
        self.assertEqual(self.b._last_answer, "", "新一轮开头上轮答案必须清掉")

    def test_chunk_after_new_turn_has_no_old_answer(self):
        self._fill("第一问", "第一轮的答案")
        self.b._start_turn("第二问")
        self.b._on_chunk("片段", replace=False, seq=self.b._turn_seq)
        self.assertEqual(self.b._last_answer, "片段")

    def test_interrupted_turn_context_not_polluted(self):
        self._fill("第一问", "第一轮的答案AAAA")
        self.b._start_turn("第二问")
        seq = self.b._turn_seq
        self.b._on_chunk("写到一半", replace=False, seq=seq)
        self.b._finish("第二问", "", "断线了", seq, "text", "")
        self.assertEqual(self.b._turns[-1], ("第二问", "写到一半"))
        self.assertEqual(self.b._turns[-1][1].count("第一轮的答案"), 0)

    def test_copy_during_stream_copies_current_only(self):
        self._fill("第一问", "第一轮的答案AAAA")
        self.b._start_turn("第二问")
        self.b._on_chunk("当前片段", replace=False, seq=self.b._turn_seq)
        self.b._copy_answer()
        clipboard = QtWidgets.QApplication.clipboard()
        self.assertEqual(clipboard.text(), "当前片段")

    def test_show_past_shows_status_hint(self):
        self.b._show_past("历史问", "历史答", "text", "")
        self.assertTrue(self.b.status.isVisible())
        self.assertIn("历史记录", self.b.status.text())
        self.assertTrue(self.b._answer_shown)
        self.assertEqual(self.b._state_name, bar.STATE_HISTORY)

    def test_usage_worker_reaped(self):
        self.b._usage_cache = None
        self.b._usage_at = 0.0
        self.b.refresh_usage()
        worker = self.b._usage_worker
        self.assertIsNotNone(worker)
        self.assertTrue(worker.wait(10000))
        QtWidgets.QApplication.processEvents()
        self.assertIsNone(self.b._usage_worker, "跑完该把引用摘掉")


class TestPickingCoversBar(unittest.TestCase):
    """框选：遮罩盖住横栏，不 hide()；截图抓不到横栏。"""

    def setUp(self):
        _app()
        self.rect = QtCore.QRect(10, 20, 300, 60)

    def test_overlay_paints_opaque_cover(self):
        ov = overlay.Overlay(cover=[self.rect])
        self.addCleanup(ov.deleteLater)
        ov.show()
        QtWidgets.QApplication.processEvents()
        image = ov.grab().toImage()
        color = image.pixelColor(self.rect.center())
        self.assertEqual(color.alpha(), 255, "横栏那块必须是不透明盖板")
        self.assertEqual((color.red(), color.green(), color.blue()),
                         (overlay.COVER.red(), overlay.COVER.green(), overlay.COVER.blue()))

    def test_pick_does_not_hide_bar(self):
        """源码口径：pick() 里不许再 bar.hide()，遮罩要带 cover。"""
        from learnsys.ask import app as app_mod
        source = pathlib.Path(app_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("self.bar.hide()", source,
                         "框选不许再隐藏横栏（遮罩盖住即可）")
        self.assertIn("overlay.Overlay(cover=[self.bar.frameGeometry()])", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
