"""Qt 窗口样式（R3.10.2）。

颜色、字号、圆角、间距全部来自 `tokens.py` → `web/css/tokens.css`；
本文件只描述「哪个控件用哪个令牌」，不写死配色。
Qt 默认跟 `config.DEFAULT_MOOD`（墨夜）；`:root` 仍是晨雾，只是不再被 Qt 默认读取。
"""
from __future__ import annotations

import pathlib
import re
import tempfile

from PySide6 import QtCore, QtGui, QtWidgets

from learnsys import config

from . import tokens as token_source
from .qss_common import QSS_COMMON
from .qss_today import QSS_TODAY

# 主按钮上的字色兜底；正常从 tokens.css 的 --on-accent 读
ON_ACCENT = "#ffffff"

# 版式常量：来自 settings.css / 施工单，不属于颜色令牌
CONTENT_MAX = 780          # `.settings-page { max-width }`
LABEL_MIN = 190            # `.setting-row` 左列
FIELD_GAP = 6              # `.setting-control` 里的垂直间距
FIELD_HSPACE = 18          # `.setting-row` 的 gap
WINDOW_SIZE = (900, 760)
WINDOW_MIN = (640, 420)
SCREEN_MARGIN = 40          # 窗口别顶到工作区边缘；标题栏也要留位置

_PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")
_RGBA = re.compile(
    r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)")
_ICON_CACHE: dict[tuple[str, str], str] = {}

QSS_TEMPLATE = QSS_COMMON + QSS_TODAY


def fit_size(preferred: tuple[int, int],
             margin: int = SCREEN_MARGIN) -> tuple[int, int]:
    """按可用工作区收缩窗口；150% 缩放下 760 高会超出笔记本屏幕。"""
    app = QtWidgets.QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return preferred
    area = screen.availableGeometry()
    width = min(preferred[0], max(480, area.width() - margin))
    height = min(preferred[1], max(360, area.height() - margin))
    return width, height


def _flat(tokens: dict[str, str]) -> dict[str, str]:
    return {key[2:].replace("-", "_"): value for key, value in tokens.items()}


def color(raw: str) -> QtGui.QColor:
    """令牌值转 QColor；支持 `rgba(r, g, b, a)` 与 `#hex`。"""
    text = str(raw or "").strip()
    match = _RGBA.match(text)
    if match:
        red, green, blue = (int(float(part)) for part in match.groups()[:3])
        alpha = float(match.group(4)) if match.group(4) is not None else 1.0
        return QtGui.QColor(red, green, blue, round(alpha * 255))
    return QtGui.QColor(text)


def _icon(kind: str, shade: str, size: tuple[int, int], width: float,
          points: list[tuple[float, float]]) -> str:
    """在临时目录画一张小 PNG 给 QSS 用（QSS 不认 SVG/内存图）。失败返回空串。"""
    key = (kind, shade)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached

    folder = pathlib.Path(tempfile.gettempdir()) / "learnsys-qt-style"
    path = folder / f"{kind}-{shade.lstrip('#')}.png"
    try:
        if not path.exists():
            folder.mkdir(parents=True, exist_ok=True)
            image = QtGui.QImage(*size, QtGui.QImage.Format.Format_ARGB32)
            image.fill(QtGui.QColor(0, 0, 0, 0))
            canvas = QtGui.QPainter(image)
            canvas.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            pen = QtGui.QPen(color(shade), width)
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            canvas.setPen(pen)
            canvas.drawPolyline(QtGui.QPolygonF(
                [QtCore.QPointF(x, y) for x, y in points]))
            canvas.end()
            if not image.save(str(path), "PNG"):
                return ""
    except OSError:
        return ""
    result = path.as_posix()
    _ICON_CACHE[key] = result
    return result


_CHECK = ((16, 16), 2.2, [(3.5, 8.5), (6.5, 11.5), (12.5, 5.0)])
_ARROW = ((10, 6), 1.4, [(1.5, 1.5), (5.0, 4.5), (8.5, 1.5)])


def render_qss(tokens: dict[str, str] | None = None,
               mood: str | None = None) -> str:
    """把令牌填进 QSS 模板；缺键用兜底，不会 KeyError。

    不传 tokens 时读 `web/css/tokens.css`，默认气质跟 `config.DEFAULT_MOOD`，
    和窗口实际使用的一致。
    """
    if tokens is None:
        tokens = token_source.read_web_tokens(mood=mood or config.DEFAULT_MOOD)
    source = tokens
    values = token_source.merged(source)
    flat = _flat(values)
    flat["font_family"] = token_source.font_family(values)
    flat["check_icon"] = _icon(
        "check", values.get("--on-accent", ON_ACCENT), *_CHECK)
    flat["arrow_icon"] = _icon(
        "arrow", values.get("--text-dim", "#9aa7b5"), *_ARROW)
    return _PLACEHOLDER.sub(lambda match: flat.get(match.group(1), ""), QSS_TEMPLATE)


def build_palette(tokens: dict[str, str] | None = None) -> QtGui.QPalette:
    """盖掉原生控件/弹层的浅色默认（下拉列表、滚动条、禁用态）。"""
    values = token_source.merged(tokens)
    palette = QtGui.QPalette()
    roles = {
        QtGui.QPalette.ColorRole.Window: values["--bg"],
        QtGui.QPalette.ColorRole.WindowText: values["--text"],
        QtGui.QPalette.ColorRole.Base: values["--bg-input"],
        QtGui.QPalette.ColorRole.AlternateBase: values["--bg-sunken"],
        QtGui.QPalette.ColorRole.Text: values["--text"],
        QtGui.QPalette.ColorRole.Button: values["--bg-raised"],
        QtGui.QPalette.ColorRole.ButtonText: values["--text"],
        QtGui.QPalette.ColorRole.BrightText: values["--text"],
        QtGui.QPalette.ColorRole.Highlight: values["--accent"],
        QtGui.QPalette.ColorRole.HighlightedText: values.get(
            "--on-accent", ON_ACCENT),
        QtGui.QPalette.ColorRole.ToolTipBase: values["--bg-raised"],
        QtGui.QPalette.ColorRole.ToolTipText: values["--text"],
        QtGui.QPalette.ColorRole.Light: values["--bg-raised"],
        QtGui.QPalette.ColorRole.Mid: values["--line"],
        QtGui.QPalette.ColorRole.Dark: values["--line-strong"],
        QtGui.QPalette.ColorRole.Shadow: values["--bg-sunken"],
        QtGui.QPalette.ColorRole.PlaceholderText: values["--text-faint"],
    }
    for role, raw in roles.items():
        palette.setColor(role, color(raw))
    for role in (QtGui.QPalette.ColorRole.WindowText,
                 QtGui.QPalette.ColorRole.Text,
                 QtGui.QPalette.ColorRole.ButtonText,
                 QtGui.QPalette.ColorRole.PlaceholderText):
        palette.setColor(QtGui.QPalette.ColorGroup.Disabled, role,
                         color(values["--text-faint"]))
    return palette


def apply_theme(window: QtWidgets.QWidget,
                tokens: dict[str, str] | None = None,
                mood: str | None = None) -> dict[str, str]:
    """给窗口装样式、调色板、字体；返回本次用到的令牌（便于测试/诊断）。

    `tokens` 明确传入时原样使用；否则读 tokens.css，并用 `mood`
    （缺省 `config.DEFAULT_MOOD` = 墨夜）覆盖 `:root` 的晨雾值。
    """
    if tokens is None:
        tokens = token_source.read_web_tokens(mood=mood or config.DEFAULT_MOOD)
    values = token_source.merged(tokens)
    window.setPalette(build_palette(values))
    window.setStyleSheet(render_qss(values))
    font = QtGui.QFont(token_source.font_family(values))
    font.setPixelSize(token_source.px(values, "--fs-base", 15))
    window.setFont(font)
    return values
