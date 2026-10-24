"""Qt 设置页的深色样式（R3.10.2）。

颜色、字号、圆角、间距全部来自 `tokens.py` → `web/css/tokens.css`；
本文件只描述「哪个控件用哪个令牌」，不写死配色。
"""
from __future__ import annotations

import pathlib
import re
import tempfile

from PySide6 import QtCore, QtGui, QtWidgets

from . import tokens as token_source

# 主按钮上的字色（Web 的 `.btn-primary` 写的就是这个值，不随主题变）
ON_ACCENT = "#0f1420"

# 版式常量：来自 settings.css / 施工单，不属于颜色令牌
CONTENT_MAX = 780          # `.settings-page { max-width }`
LABEL_MIN = 190            # `.setting-row` 左列
FIELD_GAP = 6              # `.setting-control` 里的垂直间距
FIELD_HSPACE = 18          # `.setting-row` 的 gap
WINDOW_SIZE = (900, 760)
WINDOW_MIN = (640, 420)

_PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")
_RGBA = re.compile(
    r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)")
_ICON_CACHE: dict[tuple[str, str], str] = {}

QSS_TEMPLATE = """
* {
    font-family: "{{font_family}}";
}
QDialog#SettingsWindow {
    background: {{bg}};
    color: {{text}};
    font-size: {{fs_base}};
}
QWidget#SettingsColumn, QWidget#SettingsContent {
    background: transparent;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget#qt_scrollarea_viewport {
    background: transparent;
}

QLabel {
    background: transparent;
    color: {{text}};
}
QLabel#PageTitle {
    font-size: {{fs_lg}};
    font-weight: 600;
    color: {{text}};
}
QLabel#SectionTitle {
    font-size: {{fs_md}};
    font-weight: 600;
    color: {{text}};
}
QLabel#FieldLabel {
    font-size: {{fs_sm}};
    color: {{text_dim}};
}
QLabel#Hint {
    font-size: {{fs_xs}};
    color: {{text_faint}};
}
QLabel#Small {
    font-size: {{fs_xs}};
    color: {{text_faint}};
}
QLabel#Status {
    font-size: {{fs_sm}};
    color: {{text_faint}};
}
QLabel#Status[state="info"] { color: {{text_faint}}; }
QLabel#Status[state="ok"]   { color: {{ok}}; }
QLabel#Status[state="err"]  { color: {{err}}; }

QWidget#Section {
    background: {{bg_raised}};
    border: 1px solid {{line}};
    border-radius: {{r_md}};
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: {{bg_input}};
    border: 1px solid {{line}};
    border-radius: {{r_sm}};
    padding: {{s1}} {{s3}};
    min-height: 26px;
    color: {{text}};
    font-size: {{fs_sm}};
    selection-background-color: {{accent}};
    selection-color: #0f1420;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: {{line_strong}};
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: {{accent_line}};
}
QLineEdit:read-only {
    background: {{bg_sunken}};
    color: {{text_faint}};
    border-color: {{line}};
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: {{bg_sunken}};
    color: {{text_faint}};
    border-color: {{line}};
}

QComboBox {
    padding-right: 28px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 24px;
    border: none;
    border-left: 1px solid {{line}};
    background: transparent;
}
QComboBox::down-arrow {
    image: url("{{arrow_icon}}");
    width: 10px;
    height: 6px;
}
QComboBox QAbstractItemView {
    background: {{bg_raised}};
    color: {{text}};
    font-size: {{fs_sm}};
    border: 1px solid {{line}};
    border-radius: {{r_sm}};
    padding: {{s1}};
    outline: 0;
    selection-background-color: {{accent_soft}};
    selection-color: {{text}};
}
QComboBox QAbstractItemView::item {
    padding: {{s1}} {{s2}};
    min-height: 24px;
}
QComboBox QAbstractItemView::item:selected {
    background: {{accent_soft}};
    color: {{text}};
}

QPushButton {
    background: transparent;
    border: 1px solid {{line_strong}};
    border-radius: {{r_sm}};
    color: {{text_dim}};
    padding: {{s1}} {{s3}};
    min-height: 24px;
    font-size: {{fs_sm}};
}
QPushButton:hover {
    background: {{bg_raised}};
    color: {{text}};
}
QPushButton:pressed {
    background: {{bg_input}};
}
QPushButton:focus {
    border-color: {{accent_line}};
}
QPushButton:disabled {
    background: {{bg_sunken}};
    border-color: {{line}};
    color: {{text_faint}};
}
QPushButton#Primary {
    background: {{accent}};
    border-color: {{accent}};
    color: #0f1420;
    font-weight: 600;
}
QPushButton#Primary:hover {
    background: {{accent_strong}};
    border-color: {{accent_strong}};
}
QPushButton#Primary:pressed {
    background: {{accent}};
}
QPushButton#Primary:disabled {
    background: {{bg_sunken}};
    border-color: {{line}};
    color: {{text_faint}};
}
QPushButton#Quiet {
    background: transparent;
    border-color: transparent;
    color: {{text_faint}};
    font-size: {{fs_xs}};
    padding: {{s1}} {{s2}};
}
QPushButton#Quiet:hover {
    background: {{bg_raised}};
    border-color: {{line_strong}};
    color: {{text}};
}
QPushButton#Danger {
    background: transparent;
    border: 1px solid rgba(227, 123, 123, 0.35);
    color: {{err}};
    font-size: {{fs_xs}};
    padding: {{s1}} {{s2}};
}
QPushButton#Danger:hover {
    background: {{err_soft}};
}

QCheckBox {
    background: transparent;
    color: {{text_dim}};
    font-size: {{fs_sm}};
    spacing: {{s2}};
}
QCheckBox:hover { color: {{text}}; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid {{line}};
    border-radius: 4px;
    background: {{bg_input}};
}
QCheckBox::indicator:hover { border-color: {{line_strong}}; }
QCheckBox::indicator:checked {
    background: {{accent}};
    border-color: {{accent}};
    image: url("{{check_icon}}");
}
QCheckBox::indicator:checked:hover {
    background: {{accent_strong}};
    border-color: {{accent_strong}};
}
QCheckBox::indicator:disabled {
    background: {{bg_sunken}};
    border-color: {{line}};
}

QListWidget {
    background: {{bg_sunken}};
    border: 1px solid {{line}};
    border-radius: {{r_sm}};
    padding: {{s1}};
    color: {{text}};
    outline: 0;
}
QListWidget::item {
    border-bottom: 1px solid {{line}};
    padding: {{s1}};
}
QListWidget::item:selected {
    background: {{accent_soft}};
    color: {{text}};
}

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: {{line_strong}};
    border-radius: 4px;
    min-height: 28px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover { background: {{text_faint}}; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: {{line_strong}};
    border-radius: 4px;
    min-width: 28px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: {{text_faint}}; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

QToolTip {
    background: {{bg_raised}};
    color: {{text}};
    border: 1px solid {{line}};
    padding: {{s1}} {{s2}};
    font-size: {{fs_xs}};
}
"""


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


def render_qss(tokens: dict[str, str] | None = None) -> str:
    """把令牌填进 QSS 模板；缺键用兜底，不会 KeyError。"""
    values = token_source.merged(tokens)
    flat = _flat(values)
    flat["font_family"] = token_source.font_family(values)
    flat["check_icon"] = _icon("check", ON_ACCENT, *_CHECK)
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
        QtGui.QPalette.ColorRole.HighlightedText: ON_ACCENT,
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
                tokens: dict[str, str] | None = None) -> dict[str, str]:
    """给窗口装样式、调色板、字体；返回本次用到的令牌（便于测试/诊断）。"""
    values = token_source.merged(
        tokens if tokens is not None else token_source.read_web_tokens())
    window.setPalette(build_palette(values))
    window.setStyleSheet(render_qss(values))
    font = QtGui.QFont(token_source.font_family(values))
    font.setPixelSize(token_source.px(values, "--fs-base", 15))
    window.setFont(font)
    return values
