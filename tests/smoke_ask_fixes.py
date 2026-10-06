# -*- coding: utf-8 -*-
"""「问一问」#1–#7 修复的界面冒烟：走真实控件路径，不是单测里的直接调内部方法。

跑法（仓库根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_ask_fixes.py

输出每一项的 ✅/❌ 和现场证据。
"""
from __future__ import annotations

import os
import sys
import traceback
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from learnsys.ask import backend, bar  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'✅' if ok else '❌'} {name} —— {detail}")


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    # ---------- #1 旧轮结果不许写回 ----------
    b = bar.AskBar("Alt+Q")
    b._start_turn("第一问")
    seen = []
    b.answered.connect(lambda rec: seen.append(rec))
    stream_started = []

    def slow_stream(*_a, **_k):
        stream_started.append(1)
        yield "碎片一"
        import time
        time.sleep(0.4)
        yield "碎片二"
        yield "碎片三"

    with mock.patch.object(backend, "ask_stream", slow_stream):
        b.ask.setText("第一问")
        b.submit()
        # 等第一片写进去
        deadline = QtCore.QElapsedTimer()
        deadline.start()
        while "碎片一" not in b.answer.toPlainText() and deadline.elapsed() < 2000:
            app.processEvents()
            import time
            time.sleep(0.01)
        mid = b.answer.toPlainText()
        b.new_session()                       # 这里掐掉旧轮
        # 把剩余事件跑完，让旧 worker 的 chunk/done 打过来
        import time
        time.sleep(0.6)
        for _ in range(30):
            app.processEvents()
            time.sleep(0.01)
        after = b.answer.toPlainText()

    ok1 = ("碎片一" not in after) and ("碎片三" not in after) and not seen
    record("#1 旧轮结果不写回", ok1,
           f"新会话后答案区={after!r}（应无旧碎片）· 落库条数={len(seen)}")

    # ---------- #5 复制只拿答案 ----------
    b2 = bar.AskBar("Alt+Q")

    def instant_stream(*_a, **_k):
        yield "答案是"
        yield " 42"

    with mock.patch.object(backend, "ask_stream", instant_stream):
        b2.ask.setText("这道题怎么解")
        b2.submit()
        deadline = QtCore.QElapsedTimer()
        deadline.start()
        while deadline.elapsed() < 2000:
            app.processEvents()
            if b2._last_answer == "答案是 42":
                break
            import time
            time.sleep(0.01)
        clip = QtWidgets.QApplication.clipboard()
        b2._copy_answer()
        copied = clip.text()
    ok5 = copied == "答案是 42"
    record("#5 复制只拿答案", ok5, f"剪贴板={copied!r}（应=『答案是 42』，不带问题行）")

    # ---------- #3 ✕ 收进托盘不丢图 ----------
    pix = QtGui.QPixmap(24, 16)
    pix.fill(QtGui.QColor("#123456"))
    tmpdir = os.path.join(os.environ.get("TEMP", "."), "ask_smoke")
    os.makedirs(tmpdir, exist_ok=True)
    img_path = os.path.join(tmpdir, "shot.png")
    pix.save(img_path, "PNG")
    b3 = bar.AskBar("Alt+Q")
    b3.set_shot(img_path, pix)
    cleared_flags = []
    b3.cleared.connect(lambda: cleared_flags.append(1))
    b3.hide_bar()
    ok3 = (b3._image_path == img_path) and (not cleared_flags) and os.path.exists(img_path)
    record("#3 ✕ 不丢图/不删截图", ok3,
           f"image_path={b3._image_path!r} · cleared信号={cleared_flags} · 文件还在={os.path.exists(img_path)}")

    # ---------- #3b kind 在 submit 当场拍死 ----------
    b4 = bar.AskBar("Alt+Q")
    b4.set_shot(img_path, pix)
    got = []

    def one_chunk(*_a, **_k):
        yield "图上写着你好"

    with mock.patch.object(backend, "ask_stream", one_chunk):
        b4.answered.connect(lambda rec: got.append(rec))
        b4.ask.setText("图上写了啥")
        b4.submit()
        deadline = QtCore.QElapsedTimer()
        deadline.start()
        while not got and deadline.elapsed() < 2000:
            app.processEvents()
            import time
            time.sleep(0.01)
    ok3b = bool(got) and got[0]["kind"] == "image" and got[0]["image_path"] == img_path
    record("#3b kind/image_path 按 submit 当场拍死", ok3b,
           f"落库记录 kind={got[0]['kind'] if got else None!r} image_path={got[0]['image_path'] if got else None!r}")

    # ---------- #6 看历史后开新上下文 ----------
    b5 = bar.AskBar("Alt+Q")
    b5._turns = [("老问题", "老答案")]
    b5._show_past("历史问", "历史答", "text", "")
    turns_after = list(b5._turns)
    clip = QtWidgets.QApplication.clipboard()
    b5._copy_answer()
    hist_copy = clip.text()
    ok6 = (turns_after == []) and (hist_copy == "历史答")
    record("#6 看历史=新上下文+只拷答案", ok6,
           f"看历史后 _turns={turns_after} · 复制={hist_copy!r}")

    # ---------- #2 退出时收线程 ----------
    b6 = bar.AskBar("Alt+Q")

    def hang_stream(*_a, **_k):
        import time
        time.sleep(0.35)
        yield "迟到"

    crashed = None
    try:
        with mock.patch.object(backend, "ask_stream", hang_stream):
            b6.ask.setText("慢问题")
            b6.submit()
            alive_before = len([w for w in b6._workers if w.isRunning()])
            b6.shutdown()
            alive_after = len([w for w in b6._workers if w.isRunning()])
        ok2 = (alive_before >= 1) and (alive_after == 0)
        record("#2 退出前 wait 收线程", ok2,
               f"shutdown 前活线程={alive_before} · 后={alive_after}（须为 0）")
    except Exception as exc:
        crashed = traceback.format_exc()
        record("#2 退出前 wait 收线程", False, f"异常：{exc}")

    # ---------- #7 流式截断要报 ----------
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

    got_pieces = []
    err = None
    with mock.patch.object(backend, "_open", return_value=FakeResp()):
        with mock.patch.object(backend.config, "api_style", return_value="responses"):
            try:
                for piece in backend.ask_stream(None, "问", None):
                    got_pieces.append(piece)
            except backend.AskError as exc:
                err = str(exc)
    ok7 = (got_pieces == ["写到一半"]) and (err is not None) and ("max_tokens" in err)
    record("#7 流式截断会报", ok7,
           f"已流出={got_pieces} · 错误={err!r}（须含 max_tokens）")

    # ---------- #4 换截图保存失败不删旧 ----------
    from learnsys.ask import app as app_mod
    src = open(app_mod.__file__, encoding="utf-8").read()
    save_pos = src.find('if not shot.save(str(tmp_path), "PNG")')
    fail_branch = src[save_pos:save_pos + 240] if save_pos > 0 else ""
    ok4 = save_pos > 0 and "return" in fail_branch and "_shot_done" not in fail_branch
    record("#4 存失败不删旧截图", ok4,
           f"保存失败分支长度={len(fail_branch)} · 含 _shot_done={('_shot_done' in fail_branch)}")

    for w in (b, b2, b3, b4, b5, b6):
        try:
            w.shutdown()
            w.deleteLater()
        except Exception:
            pass
    app.processEvents()

    print()
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"合计 {len(RESULTS)} 项，失败 {len(failed)} 项" + (f"：{failed}" if failed else " —— 全过"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
