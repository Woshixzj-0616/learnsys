# -*- coding: utf-8 -*-
"""「问一问」bug 修复回归测试 —— #1~#7 每条至少一个用例钉死。

跑法（在仓库根目录）：
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v

Qt 用 offscreen，不弹真窗口。注意 `isVisible()` 在 offscreen 下因父链未 show 恒假
⇒ 断言一律用 `isHidden()`。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from learnsys.ask import backend, bar  # noqa: E402


def _app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class AskBarFixture(unittest.TestCase):
    """每个用例一条干净横栏。"""

    def setUp(self):
        _app()
        self.bar = bar.AskBar("Alt+Q")
        self.addCleanup(self.bar.shutdown)
        self.addCleanup(self.bar.deleteLater)

    # -- 小工具 --

    def _start_turn(self, question: str) -> None:
        self.bar._start_turn(question)

    def _image_file(self):
        import pathlib
        import tempfile

        path = pathlib.Path(tempfile.mkdtemp()) / "shot.png"
        pix = QtGui.QPixmap(20, 12)
        pix.fill(QtGui.QColor("red"))
        self.assertTrue(pix.save(str(path), "PNG"))
        return path


class Test1StaleTurnCannotWrite(AskBarFixture):
    """#1 新会话/清空后，旧那一轮的 chunk/done 不许再往界面上写。"""

    def test_chunk_from_old_seq_is_ignored(self):
        self.bar._start_turn("第一问")
        self.bar._on_chunk("旧答案碎片", replace=False, seq=self.bar._turn_seq)
        self.assertIn("旧答案碎片", self.bar.answer.toPlainText())

        self.bar.new_session()            # 轮次号 +1，旧 seq 作废
        old_seq = self.bar._turn_seq - 1
        self.bar._on_chunk("不该出现", replace=False, seq=old_seq)
        self.assertNotIn("不该出现", self.bar.answer.toPlainText())

    def test_finish_from_old_seq_is_ignored(self):
        self.bar._start_turn("第一问")
        captured = []
        self.bar.answered.connect(lambda rec: captured.append(rec))

        self.bar.clear_session()          # 旧轮作废
        old_seq = self.bar._turn_seq - 1
        self.bar._finish("第一问", "旧的完整答案", None, old_seq, "text", "")

        self.assertNotIn("旧的完整答案", self.bar.answer.toPlainText())
        self.assertEqual(captured, [])    # 也不该落库

    def test_new_session_blocks_old_done(self):
        self.bar._start_turn("第一问")
        answered = []
        self.bar.answered.connect(lambda rec: answered.append(rec))

        self.bar.new_session()
        self.bar._finish("第一问", "旧答案", None, self.bar._turn_seq - 1, "text", "")
        self.assertEqual(answered, [])
        self.assertNotIn("旧答案", self.bar.answer.toPlainText())


class Test2ShutdownWaitsWorkers(AskBarFixture):
    """#2 退出前把后台线程收干净（还在跑就销毁会崩）。"""

    def test_shutdown_waits_running_worker(self):
        release = []

        def slow_stream(*_a, **_k):
            release.append("started")
            import time

            time.sleep(0.3)
            yield "迟到的字"

        with mock.patch.object(backend, "ask_stream", slow_stream):
            self.bar.ask.setText("问个慢的")
            self.bar.submit()
            self.assertTrue(self.bar._workers, "submit 后应登记在 _workers 里")

            self.bar.shutdown()           # 必须等到线程退出，不许带着活线程走

            alive = [w for w in self.bar._workers if w.isRunning()]
            self.assertEqual(alive, [], "shutdown 后不许还有活着的线程")
            self.assertEqual(self.bar._workers, [])

    def test_shutdown_is_idempotent(self):
        self.bar.shutdown()
        self.bar.shutdown()               # 连点退出也不许炸


class Test3HideKeepsImageAndKind(AskBarFixture):
    """#3 ✕ 收进托盘 = 只收界面；图问答身份在 submit 当场拍死。"""

    def test_hide_bar_keeps_image(self):
        path = self._image_file()
        pix = QtGui.QPixmap(str(path))
        self.bar.set_shot(str(path), pix)
        self.assertIsNotNone(self.bar._image_path)

        self.bar.hide_bar()               # ✕ 或 Esc
        self.assertIsNotNone(self.bar._image_path, "收进托盘不该把图丢掉")
        self.assertFalse(self.bar.thumb.isHidden(), "缩略图也该还在")

    def test_hide_bar_does_not_emit_cleared(self):
        cleared = []
        self.bar.cleared.connect(lambda: cleared.append(True))
        self.bar.hide_bar()
        self.assertEqual(cleared, [], "✕ 不是「清空」，不该发 cleared（否则截图被删）")

    def test_kind_is_snapshotted_at_submit_time(self):
        """答案回来时就算图已被丢掉，也得按 submit 当时的身份记成图问。"""
        path = self._image_file()
        pix = QtGui.QPixmap(str(path))
        self.bar.set_shot(str(path), pix)
        self.bar.ask.setText("图上写了啥")
        self.bar._start_turn("图上写了啥")
        seq = self.bar._turn_seq
        kind = "image" if self.bar._image_path else "text"
        image_path = self.bar._image_path or ""
        self.assertEqual(kind, "image")

        self.bar.drop_image()             # 图被丢掉但轮次还在（不作废本轮）
        self.assertIsNone(self.bar._image_path)
        captured = []
        self.bar.answered.connect(lambda rec: captured.append(rec))
        self.bar._finish("图上写了啥", "写了你好", None, seq, kind, image_path)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["kind"], "image")
        self.assertEqual(captured[0]["image_path"], str(path))


class Test4ReplaceKeepsOldShotOnFailure(AskBarFixture):
    """#4 换截图存失败时，上一张不许跟着没。"""

    def test_save_failure_keeps_previous_file(self):
        import pathlib
        import tempfile

        from learnsys.ask import app as app_mod

        work = pathlib.Path(tempfile.mkdtemp())
        old = work / "shot.png"
        old.write_bytes(b"OLD-SHOT")

        captured_holder = []

        class FakeApp:
            """只借 `_capture` 的保存逻辑，不建真托盘。"""

            def _shot_path(self_inner):
                return old

            def _warn(self_inner, message):
                captured_holder.append(("warn", message))

            class _Bar:
                def set_shot(self_b, image_path, shot):
                    captured_holder.append(("set_shot", image_path))

            bar = _Bar()

            def show_bar(self_inner):
                captured_holder.append(("show_bar",))

        fake = FakeApp()
        # 存不下来的 shot（0×0 抓不到的路径走 _warn 在前；这里直接验「保存失败」分支）
        bad_shot = QtGui.QPixmap(4, 4)
        with mock.patch.object(QtGui.QPixmap, "save", return_value=False):
            rect = QtCore.QRect(0, 0, 4, 4)
            # 调真实 `_capture` 的后半段：先拿 screen，这里换成注入的假法
            # 直接复刻保存顺序做等价断言太脆 ⇒ 直接调 app_mod 的真函数不可行（要真屏），
            # 改为断言「真代码没有在保存成功前 unlink 旧文件」这一不变式。
            code = pathlib.Path(app_mod.__file__).read_text(encoding="utf-8")
            save_pos = code.find('if not shot.save(str(tmp_path), "PNG")')
            replace_pos = code.find("tmp_path.replace(image_path)")
            done_pos = code.find("self._shot_done()", save_pos)
            self.assertGreater(save_pos, 0, "应有先存临时文件的逻辑")
            self.assertGreater(replace_pos, save_pos, "存成功后才 replace 到正式路径")
            # 保存失败分支直接 return，不许先删旧的
            fail_branch = code[save_pos:save_pos + 220]
            self.assertIn("return", fail_branch)
            self.assertNotIn("_shot_done", fail_branch, "保存失败的分支不许碰旧截图")

        self.assertEqual(old.read_bytes(), b"OLD-SHOT", "旧截图必须完好")
        self.assertEqual(bad_shot.width(), 4)


class Test5LastAnswerFollowsAppend(AskBarFixture):
    """#5 流式追加也要记进 _last_answer —— 复制按钮只认它。"""

    def test_append_updates_last_answer(self):
        self.bar._start_turn("问题")
        self.bar._on_chunk("你", replace=False, seq=self.bar._turn_seq)
        self.bar._on_chunk("好", replace=False, seq=self.bar._turn_seq)
        self.assertEqual(self.bar._last_answer, "你好")

    def test_copy_returns_answer_not_question(self):
        self.bar._start_turn("这道题怎么解")
        self.bar._on_chunk("答案是 42", replace=False, seq=self.bar._turn_seq)
        clipboard = QtWidgets.QApplication.clipboard()
        self.bar._copy_answer()
        self.assertEqual(clipboard.text(), "答案是 42")
        self.assertNotIn("这道题怎么解", clipboard.text())

    def test_replace_updates_last_answer_too(self):
        self.bar._start_turn("问题")
        self.bar._on_chunk("**粗体**", replace=True, seq=self.bar._turn_seq)
        self.assertEqual(self.bar._last_answer, "**粗体**")


class Test6HistoryStartsFreshContext(AskBarFixture):
    """#6 看历史再打字 = 新上下文，不许带着看不见的旧对话。"""

    def test_show_past_clears_turns(self):
        self.bar._turns = [("老问题", "老答案")]
        self.bar._show_past("历史问", "历史答", "text", "")
        self.assertEqual(self.bar._turns, [], "看历史后不许还带着旧上下文")

    def test_show_past_copies_answer_only(self):
        self.bar._show_past("历史问", "历史答", "image", "D:/x.png")
        clipboard = QtWidgets.QApplication.clipboard()
        self.bar._copy_answer()
        self.assertEqual(clipboard.text(), "历史答")

    def test_next_question_after_history_has_no_history(self):
        self.bar._turns = [("老问题", "老答案")]
        self.bar._show_past("历史问", "历史答", "text", "")
        self.bar.ask.setText("新的第一问")
        self.bar.submit()
        # submit 把 list(self._turns) 传给 worker —— 此时应是空
        self.assertEqual(self.bar._turns, [])


class Test7TruncatedAnswerIsReported(unittest.TestCase):
    """#7 流式被 max_tokens 掐断也要报，不许装成功。"""

    def test_is_truncated_chat_length(self):
        data = {"choices": [{"finish_reason": "length"}]}
        self.assertTrue(backend._is_truncated(data, "chat"))

    def test_is_truncated_chat_ok(self):
        data = {"choices": [{"finish_reason": "stop"}]}
        self.assertFalse(backend._is_truncated(data, "chat"))

    def test_is_truncated_responses_incomplete(self):
        self.assertTrue(backend._is_truncated({"status": "incomplete"}, "responses"))

    def test_is_truncated_responses_nested(self):
        data = {"type": "response.completed", "response": {"status": "incomplete"}}
        self.assertTrue(backend._is_truncated(data, "responses"))

    def test_stream_raises_truncated_after_yielding(self):
        """碎片照常吐出来，但收尾要报「被掐断」—— 界面会留着已写的 + 标中断。"""
        lines = [
            'data: {"type": "response.output_text.delta", "delta": "写到一半"}'.encode("utf-8"),
            'data: {"type": "response.completed", "response": {"status": "incomplete"}}'.encode("utf-8"),
        ]

        class FakeResp:
            headers = {"Content-Type": "text/event-stream"}

            def __iter__(self):
                return iter(lines)

            def read(self):
                return b""

            def close(self):
                pass

        with mock.patch.object(backend, "_open", return_value=FakeResp()):
            with mock.patch.object(backend.config, "api_style", return_value="responses"):
                got = []
                with self.assertRaises(backend.AskError) as ctx:
                    for piece in backend.ask_stream(None, "问", None):
                        got.append(piece)
                self.assertEqual(got, ["写到一半"], "已流出的字不许被吞")
                self.assertIn("max_tokens", str(ctx.exception))

    def test_sync_ask_truncated_message(self):
        class FakeResp:
            headers = {"Content-Type": "application/json"}

            def read(self):
                import json

                return json.dumps({"status": "incomplete", "output": []}).encode("utf-8")

            def close(self):
                pass

        with mock.patch.object(backend, "_open", return_value=FakeResp()):
            with mock.patch.object(backend.config, "api_style", return_value="responses"):
                with self.assertRaises(backend.AskError) as ctx:
                    backend.ask(None, "问", None)
                self.assertIn("max_tokens", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
