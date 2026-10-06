# -*- coding: utf-8 -*-
"""真链路实测：打本机 Codex 中转，走 `backend.ask_stream` + 真 `_AskWorker`/`AskBar`。

只问两句（一文一图），不刷量。跑完即退。
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from learnsys.ask import backend, bar  # noqa: E402


def wait_until(app, cond, timeout_ms=90000):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_ms / 1000:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    b = bar.AskBar("Alt+Q")
    ok = True

    # 1) 纯文字真问答
    b.ask.setText("用一句话回答：1+1等于几？只写数字。")
    b.submit()
    if not wait_until(app, lambda: bool(b._turns) or "没成功" in b.status.text() or "中断" in b.status.text()):
        print("❌ 文问超时")
        ok = False
    else:
        ans = b._last_answer
        print(f"✅ 文问真链路 —— 答案={ans!r} · 状态={b.status.text()!r}")
        if not ans.strip():
            print("❌ 答案是空的")
            ok = False

    # 2) 看图真问答（画一张带字的图）
    b.new_session()
    pix = QtGui.QPixmap(240, 80)
    pix.fill(QtGui.QColor("white"))
    p = QtGui.QPainter(pix)
    p.setPen(QtGui.QColor("black"))
    p.drawText(pix.rect(), QtCore.Qt.AlignCenter, "HELLO-42")
    p.end()
    tmp = os.path.join(os.environ.get("TEMP", "."), "ask_smoke")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, "real_shot.png")
    pix.save(path, "PNG")
    b.set_shot(path, pix)
    b.ask.setText("图上写了什么？只写那串字符。")
    b.submit()
    if not wait_until(app, lambda: bool(b._turns) or "没成功" in b.status.text() or "中断" in b.status.text()):
        print("❌ 图问超时")
        ok = False
    else:
        ans = b._last_answer
        print(f"✅ 图问真链路 —— 答案={ans!r} · 状态={b.status.text()!r}")
        if not ans.strip():
            print("❌ 答案是空的")
            ok = False

    b.shutdown()
    b.deleteLater()
    app.processEvents()
    print("真链路结果：", "全过" if ok else "有失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
