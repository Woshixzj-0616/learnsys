# -*- coding: utf-8 -*-
"""改进项的回归测试：版本可见 / 流式跟随滚动 / 占用缓存 / 框选竞态 / 截图 data URL 缓存。

对应 2026-10-06 那轮「你定个顺序开始改进」—— 每项一个测试类。
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtWidgets, QtGui  # noqa: E402

from learnsys.ask import VERSION, app as app_mod, backend, bar, usage  # noqa: E402

REPO = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _app():
    a = QtWidgets.QApplication.instance()
    if a is None:
        a = QtWidgets.QApplication([])
    return a


class TestVersionVisible(unittest.TestCase):
    """版本号只有一处来源，界面上看得见；exe 比源码旧要能判出来。"""

    def test_version_format(self):
        self.assertRegex(VERSION, r"^\d+\.\d+\.\d+$")

    def test_version_line_marks_source_run(self):
        self.assertIn("源码运行", app_mod.version_line())

    def test_newest_source_mtime(self):
        m = app_mod.newest_source_mtime(REPO / "learnsys")
        self.assertIsNotNone(m)
        self.assertGreater(m, 0.0)
        self.assertIsNone(app_mod.newest_source_mtime(pathlib.Path("Z:/不存在的目录xyz")))

    def test_stale_exe_check_skipped_for_source_runs(self):
        """源码跑（非打包）永远不算「旧 exe」—— 没得比。"""
        b = app_mod.AskApp.__dict__  # 只确认方法在
        self.assertIn("_exe_is_stale", b)
        code = pathlib.Path(app_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("if not config.FROZEN", code)


class TestStreamingFollowScroll(unittest.TestCase):
    """长答案内部滚动时：跟着最新走；用户往上翻了就别拽。"""

    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.b.show()
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)
        self.seq = self.b._turn_seq
        self.b._start_turn("问题")
        self.piece = "很长的内容用来把答案区撑到上限出现内部滚动条。" * 20
        # 喂到出内部滚动条为止 —— 字体度量各环境不同，别写死轮数
        for _ in range(40):
            if self.b.answer.verticalScrollBar().maximum() > 0:
                break
            self._feed()

    def _feed(self):
        self.b._on_chunk(self.piece, replace=False, seq=self.seq)
        self.b._fit_answer()          # 直接排，不等 80ms 节流器

    def test_answer_reaches_cap_with_scrollbar(self):
        self.assertGreater(self.b.answer.verticalScrollBar().maximum(), 0,
                           "测试前提：答案长到出现内部滚动条")

    def test_follows_bottom_when_pinned(self):
        sb = self.b.answer.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._feed()
        self.assertEqual(sb.value(), sb.maximum(), "在底部时应继续跟随最新内容")

    def test_does_not_yank_when_user_scrolled_up(self):
        sb = self.b.answer.verticalScrollBar()
        sb.setValue(0)                # 用户翻到顶
        self._feed()
        self.assertEqual(sb.value(), 0, "用户上翻后不许被拽回底部")


class TestUsageCache(unittest.TestCase):
    """占用数字缓存 5 分钟：新鲜就直接用，过期再算，失败不缓存。"""

    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def test_fresh_cache_skips_worker(self):
        info = usage.Usage(short="占 1 MB", line="缓存的那行", detail="D")
        self.b._usage_cache = info
        self.b._usage_at = time.monotonic()
        self.b.refresh_usage()
        self.assertIsNone(self.b._usage_worker, "缓存新鲜就不该再起线程")
        self.assertEqual(self.b.usage_line.text(), "缓存的那行")

    def test_expired_cache_spawns_worker(self):
        info = usage.Usage(short="占 1 MB", line="L", detail="D")
        self.b._usage_cache = info
        self.b._usage_at = time.monotonic() - 301
        self.b.refresh_usage()
        self.assertIsNotNone(self.b._usage_worker, "缓存过期该重算")
        self.b._usage_worker.wait(30000)
        QtWidgets.QApplication.processEvents()

    def test_failure_not_cached(self):
        self.b._apply_usage(RuntimeError("boom"))
        self.assertIsNone(self.b._usage_cache, "失败结果不许进缓存")


class TestCaptureRaceGuard(unittest.TestCase):
    """框选松手后的 140ms 截图延迟里，再按快捷键不许框出第二个。"""

    def test_guard_present_in_all_three_places(self):
        code = pathlib.Path(app_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("if self._capture_scheduled", code, "pick 里要有守卫")
        self.assertIn("self._capture_scheduled = True", code, "松手后要立标记")
        self.assertIn("self._capture_scheduled = False", code, "截图落地要摘标记")


class TestDataUrlCache(unittest.TestCase):
    """追问反复带同一张图 —— 读盘 + base64 只做一次，图换了（mtime 变）自动失效。"""

    def setUp(self):
        backend._data_url_cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.shot = pathlib.Path(self.tmp.name) / "shot.png"
        self.shot.write_bytes(b"FAKE-PNG-BYTES")

    def test_read_once_while_unchanged(self):
        calls = []
        real = pathlib.Path.read_bytes

        def counting(self_path):
            if self_path == self.shot:
                calls.append(1)
                return b"FAKE-PNG-BYTES"
            return real(self_path)

        with mock.patch.object(pathlib.Path, "read_bytes", counting):
            u1 = backend._data_url(str(self.shot))
            u2 = backend._data_url(str(self.shot))
        self.assertEqual(u1, u2)
        self.assertEqual(len(calls), 1, "同一张图第二次该走缓存")

    def test_rereads_after_file_replaced(self):
        u1 = backend._data_url(str(self.shot))
        os.utime(self.shot, ns=(2_000_000_000, 2_000_000_000))   # 换过的图 mtime 不同
        u2 = backend._data_url(str(self.shot))
        self.assertEqual(u1, u2, "内容没变 url 也不该变")
        stat = self.shot.stat()
        cached = backend._data_url_cache[str(self.shot)]
        self.assertEqual(cached[0], (stat.st_mtime_ns, stat.st_size), "缓存键要跟上新 mtime")

    def test_missing_file_friendly_error(self):
        try:
            backend._data_url(str(self.tmp.name + "/没有.png"))
        except backend.AskError as exc:
            self.assertIn("截图读不到", str(exc))
        else:
            self.fail("该抛 AskError")


class TestVersionRegexHelper(unittest.TestCase):
    """顺手钉住 _thumb 之类没人管的细节没有必要 —— 这里只钉版本号格式被界面引用。"""

    def test_version_used_in_bar_imports(self):
        import learnsys.ask as pkg
        self.assertTrue(re.fullmatch(r"\d+\.\d+\.\d+", pkg.VERSION))



class TestTopmostToggle(unittest.TestCase):
    """置顶开关：SetWindowPos 靠不住时（Qt 把 TOPMOST 顶回去）必须落到 setWindowFlags 兜底。

    真机踩过：窗口标志带 WindowStaysOnTopHint 时点「不置顶」，SetWindowPos 降了也白降，
    横栏照样盖着一切 —— 这组测试钉死「验证 + 兜底」两步。
    """

    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def _fake_user32(self, style_after):
        fake = mock.MagicMock()
        fake.SetWindowPos.return_value = 1
        fake.GetWindowLongW.return_value = style_after
        return fake

    def test_falls_back_when_demote_ineffective(self):
        """降级没生效（EXSTYLE 还带 TOPMOST）⇒ hint 必须从窗口标志里摘掉。"""
        import ctypes
        self.b.setWindowFlags(self.b.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        fake = self._fake_user32(0x8)          # 永远"还是置顶"
        with mock.patch.object(ctypes, "windll") as W:
            W.user32 = fake
            self.b._topmost(False)
        self.assertEqual(
            int(self.b.windowFlags()) & int(QtCore.Qt.WindowStaysOnTopHint), 0,
            "SetWindowPos 靠不住时必须走 setWindowFlags 兜底")

    def test_no_fallback_when_verify_passes(self):
        """SetWindowPos 生效（EXSTYLE 达标）⇒ 不重建窗口。"""
        import ctypes
        fake = self._fake_user32(0x0)          # 已降级成功
        with mock.patch.object(ctypes, "windll") as W:
            W.user32 = fake
            with mock.patch.object(self.b, "setWindowFlags") as sf:
                self.b._topmost(False)
        sf.assert_not_called()

    def test_promote_via_fallback_adds_hint(self):
        """置顶方向同理：没生效时兜底把 hint 加回窗口标志。"""
        import ctypes
        fake = self._fake_user32(0x0)          # 加不上，一直没 TOPMOST
        with mock.patch.object(ctypes, "windll") as W:
            W.user32 = fake
            self.b._topmost(True)
        self.assertNotEqual(
            int(self.b.windowFlags()) & int(QtCore.Qt.WindowStaysOnTopHint), 0,
            "置顶失败时兜底必须带 WindowStaysOnTopHint")


class TestMoreMenuAndClearConfirm(unittest.TestCase):
    """「⋯」收纳菜单 + 清空确认：低频操作收起来，危险动作有护栏。"""

    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def test_low_frequency_buttons_hidden_but_alive(self):
        for btn in (self.b.top_btn, self.b.clear_btn, self.b.history_btn, self.b.quiz_btn):
            self.assertTrue(btn.isHidden(), f"{btn.text()} 本体应隐藏")
        for btn in (self.b.copy_btn, self.b.star_btn, self.b.session_btn,
                    self.b.review_btn, self.b.rec_btn, self.b.more_btn):
            self.assertFalse(btn.isHidden(), f"{btn.text()} 应在横栏上")

    def test_menu_action_triggers_quiz(self):
        got = []
        self.b.quiz_requested.connect(lambda: got.append(1))
        self.b.quiz_btn.click()          # 菜单动作就是调它
        self.assertEqual(got, [1])

    def test_clear_confirm_skipped_when_empty(self):
        with mock.patch.object(QtWidgets.QMessageBox, "exec", side_effect=AssertionError("不该弹")):
            self.b._clear_with_confirm()  # 空界面：直接清，不弹框
        self.assertTrue(self.b.answer.isHidden())

    def test_clear_confirm_cancel_keeps_content(self):
        self.b._start_turn("问题")
        seq = self.b._turn_seq
        self.b._on_chunk("答案内容", replace=False, seq=seq)
        self.b._finish("问题", "答案内容", None, seq, "text", "")
        with mock.patch.object(self.b, "_confirm_clear", return_value=False):
            self.b._clear_with_confirm()
        self.assertFalse(self.b.answer.isHidden(), "点了「先不清」内容必须还在")

    def test_clear_confirm_yes_clears(self):
        self.b._start_turn("问题")
        seq = self.b._turn_seq
        self.b._on_chunk("答案内容", replace=False, seq=seq)
        self.b._finish("问题", "答案内容", None, seq, "text", "")
        with mock.patch.object(self.b, "_confirm_clear", return_value=True):
            self.b._clear_with_confirm()
        self.assertTrue(self.b.answer.isHidden(), "点了「清空」内容应被清掉")


if __name__ == "__main__":
    unittest.main(verbosity=2)
