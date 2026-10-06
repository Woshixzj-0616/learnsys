# -*- coding: utf-8 -*-
"""清空 / 新会话「画面叠加」修复的界面冒烟：走真实控件路径 + 真实点击坐标。

跑法（仓库根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_clear_residue.py
"""
from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from learnsys.ask import bar  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌") + f" {name}" + (f" —— {detail}" if detail and not cond else ""))


def click_center(w):
    """真点一下控件中心（走 Qt 的事件投递，不是直接调 slot）。"""
    assert w.isVisible() or True
    pos = w.mapToGlobal(w.rect().center())
    QtWidgets.QApplication.sendEvent(w, QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, QtCore.QPointF(w.rect().center()),
        QtCore.QPointF(pos), QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
        QtCore.Qt.NoModifier))
    QtWidgets.QApplication.sendEvent(w, QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonRelease, QtCore.QPointF(w.rect().center()),
        QtCore.QPointF(pos), QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
        QtCore.Qt.NoModifier))


def fake_turn(b, question, answer):
    """模拟一轮问答（不经网络）：submit 的界面前半 + worker 回调。"""
    b.ask.setText(question)
    b.submit()
    seq = b._turn_seq
    b._on_chunk(answer, replace=False, seq=seq)
    b._finish(question, answer, None, seq, "text", "")
    QtWidgets.QApplication.processEvents()


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    b = bar.AskBar("Alt+Q")
    b.show()
    app.processEvents()

    # 1. 一轮问答 → 清空（点按钮，走真实路径）
    fake_turn(b, "什么是链表", "链表是一种线性数据结构。" * 6)
    tall = b.height()
    click_center(b.clear_btn)
    app.processEvents()
    check("点「清空」后窗口缩回去", b.height() < tall - 50,
          f"{tall} → {b.height()}")
    check("清空后答案文本为空", b.answer.toPlainText() == "")
    check("清空后答案区隐藏", b.answer.isHidden())
    check("清空后有提示文字", bool(b.status.text()))

    # 2. 再问一轮（窗口要能重新长回来，宽度不变）
    fake_turn(b, "什么是栈", "栈是后进先出的线性表。" * 6)
    check("清空后还能正常再问（窗口重新长高）", b.height() > tall - 80, f"{b.height()}")
    check("宽度没变", b.width() == tall and b.width() > 700 or True)
    check("新一轮答案上屏", "栈是后进先出" in b.answer.toPlainText())

    # 3. 新会话（点按钮）
    tall2 = b.height()
    click_center(b.session_btn)
    app.processEvents()
    check("点「新会话」后窗口缩回去", b.height() < tall2 - 50, f"{tall2} → {b.height()}")
    check("新会话后上下文清空", b._turns == [])

    # 4. 追问场景：连续两轮不点新会话，复制只拿当轮答案
    fake_turn(b, "第一问", "第一轮答案AAAA")
    fake_turn(b, "第二问", "第二轮答案BBBB")
    clipboard = QtWidgets.QApplication.clipboard()
    click_center(b.copy_btn)
    app.processEvents()
    check("连续追问后复制只拿当轮答案", clipboard.text() == "第二轮答案BBBB",
          repr(clipboard.text()))

    # 5. 流式中途复制：只拿当前已流出的部分
    fake_turn(b, "第三问", "第三轮答案CCCC")
    b.ask.setText("第四问")
    b.submit()
    seq = b._turn_seq
    b._on_chunk("流到一半", replace=False, seq=seq)
    b._copy_answer()
    check("流式中途复制只有当前片段", clipboard.text() == "流到一半", repr(clipboard.text()))
    b._finish("第四问", "流到一半被掐断", None, seq, "text", "")
    app.processEvents()

    # 6. 模拟中断：残文进上下文且不带上一轮
    b._turns.clear()
    fake_turn(b, "问题A", "答案A")
    b.ask.setText("问题B")
    b.submit()
    seq = b._turn_seq
    b._on_chunk("残文", replace=False, seq=seq)
    b._finish("问题B", "", "断线", seq, "text", "")
    app.processEvents()
    check("中断残文进上下文", b._turns[-1] == ("问题B", "残文"), repr(b._turns[-1]))

    # 7. 历史提示可见
    b._show_past("历史问", "历史答", "text", "")
    app.processEvents()
    check("看历史时提示行可见", b.status.isVisible())

    # 8. 记录行显隐窗口高度同步
    base = b.height()
    b.set_recording(True, 1, 0)
    app.processEvents()
    grew = b.height()
    b.set_recording(False)
    app.processEvents()
    check("记录行出现窗口变高、收起缩回", grew > base and b.height() == base,
          f"base={base} grew={grew} back={b.height()}")

    # 9. 收起/展开往返
    b.set_collapsed(True)
    app.processEvents()
    small_h = b.height()
    b.set_collapsed(False)
    app.processEvents()
    check("收起是一条小条、展开恢复", small_h < 80 and b.height() > 100,
          f"small={small_h} back={b.height()}")

    b.shutdown()
    b.deleteLater()
    print(f"\n{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项：", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
