# -*- coding: utf-8 -*-
"""第二轮修复 #8–#23 的回归测试。

跑法（仓库根目录）：
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from learnsys import config, record, store  # noqa: E402
from learnsys.ask import backend, bar, hotkey  # noqa: E402


def _app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class Test8TopmostSinglePath(unittest.TestCase):
    """#8 置顶只走 SetWindowPos —— show() 不许再 setWindowFlags 重建窗口。"""

    def test_show_does_not_rebuild_window(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        before = int(b.windowFlags())
        b.show()
        b.hide()
        b.show()
        self.assertEqual(int(b.windowFlags()), before, "show() 不该改窗口标志")

    def test_toggle_updates_state_and_text(self):
        """置顶开关：状态和按钮文字必须跟着翻。

        原来这条测试钉的是「不许走 setWindowFlags（会闪）」—— 那条设计本身就是
        置顶失效的根因（SetWindowPos 在 Qt 6.11 上靠不住，降级被 Qt 顶回去）。
        新不变式：**结果正确优先**；快路径生效时不重建窗口，不生效走兜底。
        """
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        import ctypes as ctypes_mod
        fake = mock.MagicMock()
        fake.SetWindowPos.return_value = 1
        fake.GetWindowLongW.return_value = 0x8     # 汇报「已是置顶」⇒ 快路径验证通过
        with tempfile.TemporaryDirectory() as tmp:
            # ⚠️ 必须把设置文件指到临时目录 —— toggle 会写盘，别把真机的界面设置翻来翻去（真踩过）
            fake_settings = pathlib.Path(tmp) / "界面设置.json"
            fake_settings.write_text("{}", encoding="utf-8")
            with mock.patch.object(config, "SETTINGS_PATH", fake_settings),                  mock.patch.object(ctypes_mod, "windll") as W:
                W.user32 = fake
                before = b._on_top
                b.toggle_always_on_top()
        self.assertEqual(b._on_top, not before)
        self.assertEqual(b.top_btn.text(), "置顶" if b._on_top else "不置顶")

    def test_toggle_demote_corrects_flags_when_ineffective(self):
        """真机踩过的场景：启动带 hint，点「不置顶」降不下去 ⇒ 兜底必须摘 hint。"""
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        b.setWindowFlags(b.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        b._on_top = False
        import ctypes as ctypes_mod
        fake = mock.MagicMock()
        fake.SetWindowPos.return_value = 1
        fake.GetWindowLongW.return_value = 0x8     # 永远「还是置顶」（被 Qt 顶回去）
        with mock.patch.object(ctypes_mod, "windll") as W:
            W.user32 = fake
            b._topmost(False)
        self.assertEqual(int(b.windowFlags()) & int(QtCore.Qt.WindowStaysOnTopHint), 0)


class Test9ConfigWired(unittest.TestCase):
    """#9 死配置要接上；_user_int 的 0 是有效值。"""

    def test_answer_cap_follows_screen_ratio(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        area_h = b._usable().height()
        expected = max(200, int(area_h * config.ASK_BAR_ANSWER_MAX_RATIO))
        self.assertEqual(b._answer_cap, expected)

    def test_user_int_zero_is_kept(self):
        self.assertEqual(config._user_int("max_tokens", 1500),
                         config.ASK_MAX_TOKENS)
        with mock.patch.dict(config.USER, {"max_tokens": 0}):
            self.assertEqual(config._user_int("max_tokens", 1500), 0,
                             "填 0 是有效值，不许被 or-default 吃掉")

    def test_user_int_blank_falls_back(self):
        with mock.patch.dict(config.USER, {"max_tokens": ""}):
            self.assertEqual(config._user_int("max_tokens", 1500), 1500)

    def test_template_mentions_text_prompt(self):
        self.assertIn("system_prompt_text", config.SETTINGS_TEMPLATE)


class Test10HistoryTrimKeepsFirst(unittest.TestCase):
    """#10 裁剪追问上下文时第一轮（带图那轮）永远保留。"""

    def test_first_turn_survives_trim(self):
        history = [(f"问{i}", f"答{i}") for i in range(6)]
        trimmed = backend._trim_history(history)
        self.assertEqual(trimmed[0], ("问0", "答0"), "第一轮必须保留（图挂在它上面）")
        self.assertLessEqual(len(trimmed), config.ASK_HISTORY_TURNS)

    def test_short_history_untouched(self):
        history = [("问0", "答0"), ("问1", "答1")]
        self.assertEqual(backend._trim_history(history), history)

    def test_image_lands_on_real_first_question(self):
        """裁剪后 image_url 仍挂在 hist[0]，而 hist[0] 就是真正的第一问。"""
        history = [(f"问{i}", f"答{i}") for i in range(6)]
        trimmed = backend._trim_history(history)
        with mock.patch.object(backend, "_data_url", return_value="data:image/png;base64,xx"):
            messages = backend._messages("fake.png", "追问", history, "chat")
        user_msgs = [m for m in messages if m.get("role") == "user"]
        first_user = user_msgs[0]
        content = first_user["content"]
        has_image = any(
            (isinstance(p, dict) and p.get("type") == "image_url")
            for p in content
        )
        self.assertTrue(has_image, "图要挂在第一问上")
        text = next(p["text"] for p in content if p.get("type") == "text")
        self.assertEqual(text, trimmed[0][0], "挂图那句必须是真第一问")


class Test11UsageRunsOffMainThread(unittest.TestCase):
    """#11 占用数字在后台算，不许在 showEvent 里同步 walk 盘。"""

    def test_refresh_usage_is_async(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        with mock.patch.object(bar.usage, "summary",
                               side_effect=lambda: (_ for _ in ()).throw(RuntimeError("x"))):
            b.refresh_usage()                    # 不该在这里抛
            self.assertIsNotNone(b._usage_worker)

    def test_apply_usage_handles_exception(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        b._apply_usage(RuntimeError("boom"))
        self.assertIn("boom", b.usage_line.text())


class Test12CancelClosesConnection(unittest.TestCase):
    """#12 取消要把底层连接一起掐断，不许挂到 90 秒超时。"""

    def test_cancel_sets_abort_and_closes_response(self):
        _app()
        b = bar.AskBar("Alt+Q")
        self.addCleanup(b.shutdown)
        self.addCleanup(b.deleteLater)
        w = bar._AskWorker(None, "问", [], b)
        closed = []

        class FakeResp:
            def close(self):
                closed.append(1)

        w._sink.append(FakeResp())
        w.cancel()
        self.assertTrue(w._abort.is_set(), "abort 事件要置位")
        self.assertEqual(closed, [1], "底层响应要被 close")

    def test_ask_stream_stops_on_abort(self):
        class FakeResp:
            headers = {"Content-Type": "text/event-stream"}
            def __iter__(self):
                yield 'data: {"type": "response.output_text.delta", "delta": "字"}'.encode("utf-8")
                yield 'data: {"type": "response.output_text.delta", "delta": "不该出"}'.encode("utf-8")
            def read(self):
                return b""
            def close(self):
                pass

        import threading
        abort = threading.Event()
        abort.set()                          # 一开跑就要求取消
        with mock.patch.object(backend, "_open", return_value=FakeResp()):
            with mock.patch.object(backend.config, "api_style", return_value="responses"):
                got = list(backend.ask_stream(None, "问", None, abort=abort))
        self.assertEqual(got, [], "abort 后不许再吐字")


class Test14PickWhileBusySpeaksUp(unittest.TestCase):
    """#14 忙时点框选不许闷声吞掉。"""

    def test_pick_busy_shows_message(self):
        from learnsys.ask import app as app_mod

        _app()
        a = app_mod.AskApp.__new__(app_mod.AskApp)
        a.snip = None
        a.bar = mock.MagicMock()
        a.bar.busy = True
        a.pick()
        a.bar.show_message.assert_called_once()
        self.assertIn("还在写", a.bar.show_message.call_args[0][0])


class Test1516SwitchCounting(unittest.TestCase):
    """#15 切换次数不含首条；#16 跨天清零。"""

    def test_first_sample_is_not_a_switch(self):
        conn = store.connect(":memory:")
        sid = store.start_session(conn)
        # 3 行 = 开始看的那个 + 2 次切换
        store.add_window_event(conn, sid, "a.exe", "A")
        store.add_window_event(conn, sid, "b.exe", "B")
        store.add_window_event(conn, sid, "c.exe", "C")
        summary = store.session_summary(conn, sid)
        self.assertEqual(summary["切换"], 2, "首条不是切换")

    def test_record_counts_only_real_switches(self):
        _app()
        rec = record.WindowRecorder(lambda: store.connect(":memory:"))
        with mock.patch.object(record, "capture") as cap, \
             mock.patch.object(record.config, "db_path",
                               return_value=__import__("pathlib").Path("x/learnsys.db")):
            cap.sample.side_effect = [("a.exe", "A"), ("a.exe", "A"), ("b.exe", "B")]
            rec._conn = store.connect(":memory:")
            rec._db_path = __import__("pathlib").Path("x/learnsys.db")
            rec._session_id = store.start_session(rec._conn)
            rec._started_at = store.now()
            rec._last = None
            rec._switches = 0
            rec._tick()          # 第一条
            rec._tick()          # 没变
            rec._tick()          # 切到 b
        self.assertEqual(rec._switches, 1, "3 次采样只该算 1 次切换")


class Test1719Messages(unittest.TestCase):
    """#17 backend 记真实模型名；#19 热键报错指向 设置.json。"""

    def test_hotkey_error_points_to_settings_json(self):
        h = hotkey.GlobalHotkey("alt+q")
        with mock.patch.object(hotkey.user32, "RegisterHotKey", return_value=0), \
             mock.patch.object(hotkey.kernel32, "GetLastError", return_value=1409):
            msgs = []
            h.failed.connect(msgs.append)
            h.register()
        self.assertTrue(msgs)
        self.assertIn("设置.json", msgs[0])
        self.assertNotIn("config.py", msgs[0])


class Test20DataUrlHumanError(unittest.TestCase):
    """#20 截图读不到要报人话，不许裸异常。"""

    def test_missing_file_gives_ask_error(self):
        with self.assertRaises(backend.AskError) as ctx:
            backend._data_url("D:/不存在的文件.png")
        self.assertIn("截图", str(ctx.exception))

    def test_empty_path_gives_ask_error(self):
        with self.assertRaises(backend.AskError):
            backend._data_url("")


class Test21ThinkingHeuristic(unittest.TestCase):
    """#21 铺垫识别别误伤正常回答。"""

    def test_long_paragraph_not_treated_as_thinking(self):
        long_para = "先看题干里给的条件，然后结合图上第二行的数字，经过计算可以得出答案是 42，请核对。"
        self.assertGreater(len(long_para), 40)
        self.assertFalse(backend._looks_like_thinking(long_para))

    def test_short_lead_in_still_detected(self):
        self.assertTrue(backend._looks_like_thinking("让我看看这张图。"))

    def test_normal_answer_untouched(self):
        self.assertFalse(backend._looks_like_thinking("答案是 42。"))


class Test22MultiScreenCapture(unittest.TestCase):
    """#22 跨屏框选按屏裁剪拼接，不再只抓一块屏。"""

    def test_capture_uses_all_screens(self):
        import pathlib
        src = pathlib.Path(
            pathlib.Path(__file__).resolve().parent.parent / "learnsys" / "ask" / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("for screen in QtGui.QGuiApplication.screens()", src)
        self.assertNotIn("screenAt(rect.center())", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
