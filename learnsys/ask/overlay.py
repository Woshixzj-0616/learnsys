"""全屏遮罩：拖一个矩形，把这块屏「框」出来。

选区外压暗、选区内透出真实屏幕；坐标一律用 Qt 的**逻辑像素**（Qt6 自己就是 DPI 感知的），
松手时发出的是覆盖所有屏幕的全局坐标。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

DIM = QtGui.QColor(0, 0, 0, 110)
EDGE = QtGui.QColor(90, 170, 255)
TEXT = QtGui.QColor(255, 255, 255, 235)
PLATE = QtGui.QColor(20, 22, 26, 200)
MIN_SIDE = 8


class Overlay(QtWidgets.QWidget):
    selected = QtCore.Signal(QtCore.QRect)   # 选中的矩形（全局逻辑坐标）
    cancelled = QtCore.Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        area = QtCore.QRect()
        for screen in QtGui.QGuiApplication.screens():
            area = area.united(screen.geometry())
        self._origin = area.topLeft()
        self.setGeometry(area)
        self._start = None
        self._cur = None

    # ---- 画 ----

    def _sel(self) -> QtCore.QRect:
        return QtCore.QRect(self._start, self._cur).normalized()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        whole = self.rect()
        if self._start is None or self._cur is None:
            painter.fillRect(whole, DIM)
        else:
            sel = self._sel()
            painter.fillRect(QtCore.QRect(whole.left(), whole.top(), whole.width(), sel.top() - whole.top()), DIM)
            painter.fillRect(QtCore.QRect(whole.left(), sel.bottom() + 1, whole.width(), whole.bottom() - sel.bottom()), DIM)
            painter.fillRect(QtCore.QRect(whole.left(), sel.top(), sel.left() - whole.left(), sel.height()), DIM)
            painter.fillRect(QtCore.QRect(sel.right() + 1, sel.top(), whole.right() - sel.right(), sel.height()), DIM)
            painter.setPen(QtGui.QPen(EDGE, 2))
            painter.drawRect(sel.adjusted(0, 0, -1, -1))
            self._draw_size(painter, sel)
        self._draw_hint(painter, whole)

    def _plate(self, painter, text, center):
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        box = painter.fontMetrics().boundingRect(text).adjusted(-14, -8, 14, 8)
        box.moveCenter(center)
        painter.fillRect(box, PLATE)
        painter.setPen(TEXT)
        painter.drawText(box, QtCore.Qt.AlignCenter, text)

    def _draw_size(self, painter, sel):
        text = f"{sel.width()} × {sel.height()}"
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        box = painter.fontMetrics().boundingRect(text).adjusted(-14, -8, 14, 8)
        top = sel.top() - box.height() // 2 - 10
        center = QtCore.QPoint(sel.center().x(), top) if top > self.rect().top() + box.height() \
            else QtCore.QPoint(sel.center().x(), sel.bottom() + box.height() // 2 + 10)
        painter.setPen(QtCore.Qt.NoPen)
        self._plate(painter, text, center)

    def _draw_hint(self, painter, whole):
        self._plate(painter, "拖拽选择区域    ·    Esc 取消",
                    QtCore.QPoint(whole.center().x(), whole.top() + 72))

    # ---- 交互 ----

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus(QtCore.Qt.OtherFocusReason)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._start = event.position().toPoint()
            self._cur = self._start
            self.update()
        elif event.button() == QtCore.Qt.RightButton:
            self._cancel()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._cur = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or self._start is None:
            return
        sel = self._sel()
        self._start = None
        self._cur = None
        if sel.width() < MIN_SIDE or sel.height() < MIN_SIDE:
            self._cancel()
            return
        self.selected.emit(sel.translated(self._origin))
        self.close()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self._cancel()

    def _cancel(self):
        self.cancelled.emit()
        self.close()
