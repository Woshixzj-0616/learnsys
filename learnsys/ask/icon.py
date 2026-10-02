"""「问一问」的图标：蓝底白「问」。

托盘 / 窗口 / 任务栏 / .ico 文件全用同一张 —— 画法只有 `pixmap()` 一处，别处只取不画。
"""
from __future__ import annotations

import pathlib
import struct

from PySide6 import QtCore, QtGui

from learnsys import config

SIZES = (16, 24, 32, 48, 64, 128, 256)      # .ico 里塞这几档，任务栏 / 开始菜单各自挑合适的


def pixmap(size: int = 64) -> QtGui.QPixmap:
    """画一张方形图标（尺寸按参数走，不写死像素）。"""
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setBrush(QtGui.QColor("#2d6cdf"))
    painter.setPen(QtCore.Qt.NoPen)
    side = float(size)
    painter.drawRoundedRect(QtCore.QRectF(0.0, 0.0, side, side), side * 0.25, side * 0.25)
    painter.setPen(QtGui.QColor("white"))
    font = painter.font()
    font.setPixelSize(max(8, round(size * 0.55)))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), QtCore.Qt.AlignCenter, "问")
    painter.end()
    return pix


def _png(size: int) -> bytes:
    """把某一档图标编码成 PNG（.ico 里装的其实就是它）。"""
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    pixmap(size).save(buf, "PNG")
    return bytes(buf.data())


def ensure_ico() -> pathlib.Path | None:
    """生成多尺寸 .ico；已经有了就复用。失败返回 None（界面照常能跑）。"""
    path = config.ICON_PATH
    try:
        if path.exists() and path.stat().st_size > 0:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        blobs = [_png(size) for size in SIZES]
        head = struct.pack("<HHH", 0, 1, len(SIZES))          # 0=图标 1=图标集 后面跟几张
        offset = len(head) + 16 * len(SIZES)
        table = b""
        body = b""
        for size, blob in zip(SIZES, blobs):
            edge = 0 if size >= 256 else size                 # 0 在 .ico 里就代表 256
            table += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(blob), offset)
            offset += len(blob)
            body += blob
        path.write_bytes(head + table + body)
        return path
    except Exception:
        return None


def icon() -> QtGui.QIcon:
    """Qt 图标（托盘 / 窗口 / 任务栏一律用它）。"""
    path = ensure_ico()
    if path is not None:
        return QtGui.QIcon(str(path))
    return QtGui.QIcon(pixmap())
