"""窗口位置与几何：置顶、两档高度、拖动、答案区改高、折叠。"""
from __future__ import annotations

import json

from PySide6 import QtCore, QtGui, QtWidgets

from learnsys import config
from .common import (BAR_OUTER_TOP, BAR_OUTER_X, MOVE_SLOP, PILL_H,
                     _LINE_HEIGHT_PROPORTIONAL)


class LayoutMixin:
    def _load_state(self) -> dict:
        try:
            data = json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _load_answer_h(self) -> int:
        """答案面板高度：上次拖到多少就恢复多少，夹在 [最矮, 屏高上限] 之间。"""
        try:
            value = int(self._state.get("answer_h", config.ASK_BAR_ANSWER_DEFAULT_H))
        except (TypeError, ValueError):
            value = config.ASK_BAR_ANSWER_DEFAULT_H
        return max(config.ASK_BAR_ANSWER_MIN_H, min(value, self._answer_cap))

    def _save_state(self) -> None:
        state = dict(self._state)
        state["x"], state["y"] = self.x(), self.y()
        state["collapsed"] = self._collapsed
        state["answer_h"] = self._answer_h
        self._state = state
        try:
            config.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            config.SETTINGS_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    def _usable(self) -> QtCore.QRect:
        area = QtCore.QRect()
        for screen in QtGui.QGuiApplication.screens():
            area = area.united(screen.availableGeometry())
        return area

    def _full_width(self) -> int:
        screen = QtGui.QGuiApplication.primaryScreen()
        wanted = int(screen.availableGeometry().width() * config.ASK_BAR_WIDTH_RATIO)
        return max(760, min(wanted, config.ASK_BAR_WIDTH_MAX))

    def _calc_answer_cap(self) -> int:
        """答案区高度上限 = 屏幕可用高度 × `ASK_BAR_ANSWER_MAX_RATIO`（再长就滚动）。"""
        area = self._usable()
        return max(200, int(area.height() * config.ASK_BAR_ANSWER_MAX_RATIO))

    def _clamp(self) -> None:
        """把窗口完整放回可用屏幕内。

        旧版只留 90px 在屏内，展开时右端会伸出屏幕、压到浏览器右上角的
        最小化/最大化按钮（真踩过）。这里改成整窗完整包含。
        """
        area = self._usable()
        max_x = area.right() - self.width() + 1
        max_y = area.bottom() - self.height() + 1
        x = max(area.left(), min(self.x(), max_x))
        y = max(area.top(), min(self.y(), max_y))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _place_default(self) -> None:
        area = self._usable()
        self.move(area.left() + (area.width() - self.width()) // 2,
                  area.top() + config.ASK_BAR_TOP_GAP)

    def _restore_place(self) -> None:
        self._collapsed = bool(self._state.get("collapsed"))
        self._apply_geometry()
        x, y = self._state.get("x"), self._state.get("y")
        area = self._usable()
        if isinstance(x, int) and isinstance(y, int) and area.contains(QtCore.QPoint(x, y)):
            self.move(x, y)
        else:
            self._place_default()

    def center_top(self) -> None:
        """回到屏幕正上方居中（托盘里那一条）。"""
        self._place_default()
        self._save_state()

    def _apply_flags(self) -> None:
        # 用 Tool（不是 Window）：横栏不进任务栏、也不进 Alt+Tab。
        # 统一入口是「学习工作台」快捷方式；横栏靠 Alt+Q / 托盘唤起，不需要任务栏按钮。
        # ⚠️ 只在建窗时调一次：`setWindowFlags` 会把窗口藏掉再重建（闪一下），
        # 置顶与否后面一律走 `_topmost`（SetWindowPos 只动层级、窗口本身不动）。
        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool
        if self._on_top:
            flags |= QtCore.Qt.WindowStaysOnTopHint
        if int(self.windowFlags()) != int(flags):
            self.setWindowFlags(flags)

    def _topmost(self, on: bool) -> None:
        """置顶 / 取消置顶。

        原本只调 SetWindowPos(HWND_TOPMOST/NOTOPMOST)，想免掉 setWindowFlags 的闪动 ——
        真机实测这条路在 Qt 6.11 上**不可靠**：窗口标志里带着 WindowStaysOnTopHint 时，
        Qt 按缓存的标志反复把 WS_EX_TOPMOST 顶回去，SetWindowPos 降了也白降
        （真踩过：点「不置顶」横栏照样盖着一切）。所以改成：
        ① 先试无闪动的 SetWindowPos（参数补齐 argtypes）；
        ② 用 GetWindowLongW 验证实际状态，达标就收工；
        ③ 不达标老实走 setWindowFlags 重建窗口（闪一下 —— 罕见操作，对 > 快）。
        """
        try:
            import ctypes
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            hwnd = wt.HWND(int(self.winId()))
            user32.SetWindowPos(hwnd, wt.HWND(-1 if on else -2), 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0010)   # 不改大小/位置、不抢焦点
            style = user32.GetWindowLongW(hwnd, -20)         # GWL_EXSTYLE
            if bool(style & 0x8) == on:                      # WS_EX_TOPMOST 与目标一致 ⇒ 成功
                return
        except Exception:
            pass
        # 兜底：改 Qt 窗口标志（窗口会重建、闪一下），位置先记下来再还原。
        # ⚠️ 这里也必须用 Tool：若写回 Window，切一次置顶任务栏按钮就复现了。
        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool
        if on:
            flags |= QtCore.Qt.WindowStaysOnTopHint
        if int(self.windowFlags()) != int(flags):
            pos = self.pos()
            self.setWindowFlags(flags)
            self.show()
            self.move(pos)

    def toggle_always_on_top(self) -> None:
        """「置顶」开关：开着才挡别的界面；默认关。"""
        self._on_top = not self._on_top
        self._state["always_on_top"] = self._on_top
        self._topmost(self._on_top)     # 层级只走这一条 —— 别再 setWindowFlags（会闪）
        self._save_state()
        self.show_message("已开置顶 —— 横栏会一直在别的窗口上面。" if self._on_top
                          else "已关置顶 —— 别的窗口可以盖住横栏。")
        self._sync_top_btn()

    def show(self) -> None:
        # 不在这儿 `_apply_flags()`：那会 `setWindowFlags` 重建窗口（闪一下）。
        # 窗口标志建窗时已定，置顶与否由 `showEvent` 里的 `_topmost` 维持。
        super().show()

    def _apply_geometry(self) -> None:
        """窗口尺寸的唯一出口：只由「收起与否 + 答案面板显隐 + 面板高度」决定。

        不再 `adjustSize()`、不再让布局按内容算尺寸 —— 内容变化永远不触发这里，
        所以流式、状态文字、录制信息都不会让窗口跳。
        """
        if self._collapsed:
            self.card.setVisible(False)
            self.pill.setVisible(True)
            width = config.ASK_BAR_PILL_WIDTH + 2 * BAR_OUTER_X
            height = PILL_H + BAR_OUTER_TOP
        else:
            self.pill.setVisible(False)
            self.card.setVisible(True)
            width = self._full_width() + 2 * BAR_OUTER_X
            card_h = self._expanded_card_h() if self._answer_shown else self._compact_card_h()
            height = card_h + BAR_OUTER_TOP
        size = QtCore.QSize(width, height)
        if self.minimumSize() != size or self.maximumSize() != size:
            self.setFixedSize(size)

    def _resize_answer(self, delta: int) -> None:
        """拖答案底边：只改面板高度，窗口高度跟着固定几何一起算。"""
        if self._drag_base is None:
            self._drag_base = self._answer_h
        height = max(config.ASK_BAR_ANSWER_MIN_H,
                     min(self._drag_base + delta, self._answer_cap))
        if height == self._answer_h:
            return
        self._answer_h = height
        self.answer.setFixedHeight(height)
        self._apply_geometry()

    def _finish_resize(self) -> None:
        self._drag_base = None
        self._save_state()

    def set_collapsed(self, flag: bool) -> None:
        if flag == self._collapsed:
            return
        self._collapsed = flag
        self._apply_geometry()
        self._clamp()
        if not flag:
            self.ask.setFocus(QtCore.Qt.OtherFocusReason)
        self._save_state()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def _place(self) -> None:                      # 兼容旧调用
        self._place_default()

    def _set_answer(self, text: str) -> None:
        self.answer.setPlainText(text)
        fmt = QtGui.QTextBlockFormat()
        fmt.setLineHeight(165.0, _LINE_HEIGHT_PROPORTIONAL)
        cursor = self.answer.textCursor()
        cursor.select(QtGui.QTextCursor.Document)
        cursor.mergeBlockFormat(fmt)
        self.answer.moveCursor(QtGui.QTextCursor.Start)
        self._set_copy_enabled(bool(text.strip()))

    def _set_copy_enabled(self, on: bool) -> None:
        """「复制」**永远占着位置**，只切换能不能点。

        它一显隐，整排按钮就会跟着挪一格 ⇒ 用户按记忆中的位置点，就会点到旁边那个。
        """
        self.copy_btn.setEnabled(on)

    def _sync_top_btn(self) -> None:
        if not hasattr(self, "top_btn"):
            return
        # 文案写当前状态，不写动作：旧版开着时叫「置顶」，用户以为点了才会置顶，
        # 结果一点反而关掉（真踩过）。现在「已置顶」= 正开着，点一下关。
        self.top_btn.setText("已置顶" if self._on_top else "置顶")
        self.top_btn.setToolTip(
            "横栏正压在其他窗口上面；点一下取消" if self._on_top
            else "点一下让横栏一直在其他窗口上面")
        self.top_btn.setChecked(self._on_top)


    def showEvent(self, event):
        super().showEvent(event)
        self._answer_cap = self._calc_answer_cap()   # 分辨率/屏幕可能变了，重算
        self._answer_h = max(config.ASK_BAR_ANSWER_MIN_H,
                             min(self._answer_h, self._answer_cap))
        self.answer.setFixedHeight(self._answer_h)
        self._apply_geometry()
        self.refresh_usage()
        self._clamp()
        self.raise_()
        if not self._collapsed:
            self.activateWindow()
            self.ask.setFocus(QtCore.Qt.OtherFocusReason)
        self._topmost(self._on_top)      # 每次露出来都重申一遍层级（别的窗口可能盖过它）

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.hide_bar()
        else:
            super().keyPressEvent(event)

    # 拖动：空白处 / 缩略图 / 小条上按住就能挪；点一下小条 = 展开
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._grab = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press = event.globalPosition().toPoint()
            self._moved = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._grab is None:
            super().mouseMoveEvent(event)
            return
        point = event.globalPosition().toPoint()
        if (point - self._press).manhattanLength() > MOVE_SLOP:
            self._moved = True
        self.move(point - self._grab)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._grab is None:
            super().mouseReleaseEvent(event)
            return
        self._grab = None
        if self._moved:
            self._clamp()
            self._save_state()
        elif self._collapsed:
            self.set_collapsed(False)               # 收起时点一下 = 展开
        event.accept()

    def hide_bar(self) -> None:
        """✕：收进托盘 —— 程序不退。**只收界面**，图、答案、上下文都留着，叫回来接着用。

        原来这里顺手 `drop_image()` + 发 `exited` 让 app 删临时截图 —— 那是把
        「收起」当成了「清空」，正在问的那轮会被记成纯文字、截图也没了。
        删截图只归「清空 / 换一张 / 退出」管。
        """
        self._save_state()
        self.hide()
        self.exited.emit()
