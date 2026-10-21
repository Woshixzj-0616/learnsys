"""「学习工作台」的图标：深蓝渐变底 + 白色书页 + 青色光点。

托盘 / 横栏 / favicon / .ico / PWA PNG 全用这一张 —— 画法只有 `pixmap()` 一处，
`tools/make_icons.py` 只是把它按不同尺寸、不同用途导出，别处只取不画。
"""
from __future__ import annotations

import pathlib
import struct

from PySide6 import QtCore, QtGui

from learnsys import config

SIZES = (16, 24, 32, 48, 64, 128, 256)      # .ico 里塞这几档，任务栏 / 开始菜单各自挑合适的


def _qpoint(size: float, x: float, y: float) -> QtCore.QPointF:
    return QtCore.QPointF(x * size, y * size)


def _page_path(size: float, left: bool) -> QtGui.QPainterPath:
    """一页书：从书脊上端弯到外缘，再收回到书脊下端。"""
    sx = 0.50 * size
    outer_x = (0.235 if left else 0.765) * size
    dirn = -1 if left else 1
    path = QtGui.QPainterPath()
    path.moveTo(sx, 0.555 * size)
    path.cubicTo(
        sx + dirn * 0.07 * size, 0.515 * size,
        sx + dirn * 0.17 * size, 0.512 * size,
        outer_x, 0.545 * size,
    )
    path.lineTo(outer_x, 0.705 * size)
    path.cubicTo(
        sx + dirn * 0.17 * size, 0.682 * size,
        sx + dirn * 0.07 * size, 0.700 * size,
        sx, 0.760 * size,
    )
    path.closeSubpath()
    return path


def _small_book_path(size: float, left: bool) -> QtGui.QPainterPath:
    """16–24px 用的简化书页：只用直线，页脊留 1px 缝，任务栏里才能看出是「摊开的书」。"""
    sx = (0.47 if left else 0.53) * size
    outer_x = (0.24 if left else 0.76) * size
    path = QtGui.QPainterPath()
    path.moveTo(sx, 0.555 * size)
    path.lineTo(outer_x, 0.535 * size)
    path.lineTo(outer_x, 0.700 * size)
    path.lineTo(sx, 0.755 * size)
    path.closeSubpath()
    return path


def pixmap(size: int = 64, *, maskable: bool = False) -> QtGui.QPixmap:
    """画一张方形图标（尺寸按参数走，不写死像素）。

    maskable=True：全出血（不留透明圆角）、图形缩进安全区，给 PWA maskable /
    Apple touch 用，避免被系统裁掉书页或光点。
    """
    side = float(size)
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.transparent)

    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    # ---- 底：深海军蓝 → 宝蓝的斜向渐变 ----
    gradient = QtGui.QLinearGradient(0.0, 0.0, side, side)
    gradient.setColorAt(0.0, QtGui.QColor("#081A44"))
    gradient.setColorAt(0.55, QtGui.QColor("#123C8C"))
    gradient.setColorAt(1.0, QtGui.QColor("#2B6BFF"))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(gradient)
    if maskable:
        painter.drawRect(QtCore.QRectF(0.0, 0.0, side, side))
    else:
        radius = side * 0.225
        painter.drawRoundedRect(QtCore.QRectF(0.0, 0.0, side, side), radius, radius)

    # ---- 左上角的一层柔光，让渐变不那么平 ----
    if size >= 32:
        glow = QtGui.QRadialGradient(side * 0.22, side * 0.12, side * 0.75)
        glow.setColorAt(0.0, QtGui.QColor(255, 255, 255, 42))
        glow.setColorAt(0.55, QtGui.QColor(255, 255, 255, 10))
        glow.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
        painter.setBrush(glow)
        painter.drawEllipse(QtCore.QRectF(-side * 0.35, -side * 0.55,
                                          side * 1.15, side * 1.15))

    # maskable 把图形整体缩小一点，保证在圆形安全区内
    if maskable:
        painter.translate(side * 0.5, side * 0.56)
        painter.scale(0.82, 0.82)
        painter.translate(-side * 0.5, -side * 0.56)

    # ---- 书页 ----
    page_gradient = QtGui.QLinearGradient(0.0, side * 0.50, 0.0, side * 0.78)
    page_gradient.setColorAt(0.0, QtGui.QColor("#FFFFFF"))
    page_gradient.setColorAt(1.0, QtGui.QColor("#DCEBFF"))
    painter.setBrush(page_gradient)
    painter.setPen(QtCore.Qt.NoPen)
    if size <= 24:
        painter.drawPath(_small_book_path(side, True))
        painter.drawPath(_small_book_path(side, False))
    else:
        painter.drawPath(_page_path(side, True))
        painter.drawPath(_page_path(side, False))
        # 书脊：一条很淡的浅蓝细缝，让两页分得开
        pen = QtGui.QPen(QtGui.QColor(111, 168, 255, 170))
        pen.setWidthF(max(1.0, side * 0.010))
        pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(_qpoint(side, 0.500, 0.575), _qpoint(side, 0.500, 0.748))

    # ---- 光点：书页上方的主光点 +（大尺寸才有的）两粒小光点 ----
    if size <= 24:
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#A9ECFF"))
        painter.drawEllipse(_qpoint(side, 0.500, 0.375), side * 0.095, side * 0.095)
    else:
        # 书脊那支蓝色画笔到此为止 —— 光晕/光点不要描边（否则会多出一圈大圆环）
        painter.setPen(QtCore.Qt.NoPen)
        halo = QtGui.QRadialGradient(side * 0.5, side * 0.375, side * 0.22)
        halo.setColorAt(0.0, QtGui.QColor(105, 216, 255, 120))
        halo.setColorAt(0.55, QtGui.QColor(105, 216, 255, 34))
        halo.setColorAt(1.0, QtGui.QColor(105, 216, 255, 0))
        painter.setBrush(halo)
        painter.drawEllipse(_qpoint(side, 0.500, 0.375), side * 0.22, side * 0.22)
        painter.setBrush(QtGui.QColor("#A9ECFF"))
        painter.drawEllipse(_qpoint(side, 0.500, 0.375), side * 0.082, side * 0.082)
        if size >= 48:
            painter.setBrush(QtGui.QColor(175, 238, 255, 210))
            painter.drawEllipse(_qpoint(side, 0.655, 0.305), side * 0.024, side * 0.024)
            painter.setBrush(QtGui.QColor(175, 238, 255, 150))
            painter.drawEllipse(_qpoint(side, 0.715, 0.405), side * 0.016, side * 0.016)

    # ---- 内侧细描边（大尺寸才加，16px 会脏）----
    if size >= 48 and not maskable:
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 34))
        pen.setWidthF(max(1.0, side * 0.006))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(pen)
        inset = side * 0.012
        radius = side * 0.225 - inset
        painter.drawRoundedRect(
            QtCore.QRectF(inset, inset, side - inset * 2, side - inset * 2),
            max(1.0, radius), max(1.0, radius),
        )

    painter.end()
    return pix


def _png(size: int, *, maskable: bool = False) -> bytes:
    """把某一档图标编码成 PNG（.ico 里装的其实就是它）。"""
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    pixmap(size, maskable=maskable).save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: pathlib.Path, *, force: bool = False,
              maskable: bool = False) -> pathlib.Path | None:
    """生成多尺寸 .ico；`force=False` 时已有文件就直接复用。失败返回 None。"""
    try:
        if not force and path.exists() and path.stat().st_size > 0:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        blobs = [_png(size, maskable=maskable) for size in SIZES]
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


def ensure_ico() -> pathlib.Path | None:
    """托盘 / favicon 用的 .ico：没有就按当前画法生成一份。"""
    return write_ico(config.ICON_PATH)


def icon() -> QtGui.QIcon:
    """Qt 图标（托盘 / 横栏窗口一律用它）。"""
    path = ensure_ico()
    if path is not None:
        return QtGui.QIcon(str(path))
    return QtGui.QIcon(pixmap())
