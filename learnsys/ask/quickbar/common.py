"""快捷栏的样式、几何常量、状态名与小工具函数（改样式先看这里）。"""
from __future__ import annotations

import re

from PySide6 import QtCore, QtGui

from ..qt import style
from ..qt import tokens as token_source


# 横栏固定跟「墨夜」气质走：它浮在桌面/浏览器上，深色不刺眼；
# 网页工作台仍默认晨雾。两套颜色都来自同一份 tokens.css，不另抄。
BAR_MOOD = "ink"

# 设计规范（改样式先看这里，别一处一处试）：
#   颜色  全部来自 `web/css/tokens.css`（`body[data-mood="ink"]`），这里只写占位符
#   强调  问 / 复盘 / 输入焦点 / 菜单选中 = --accent
#   语义  清空=危险（悬停泛红）｜ 收藏=金色（已收藏★）｜ 置顶开=蓝字
#   圆角  卡片 14 ｜ 输入/按钮/答案 10 ｜ 小按钮 8 ｜ 菜单 10
#   字号  答案 15 ｜ 输入/主按钮 14 ｜ 小按钮 13 ｜ 状态 12 ｜ 占用/记录 11
#   ⚠️ 按钮宽度 BUTTON_W 恒定、位置不动 —— 美化不许破坏肌肉记忆（见按钮行注释）
QSS_TEMPLATE = """
QFrame#bar { background: {{surface}}; border: 1px solid {{line_strong}}; border-radius: 14px;
             font-family: "{{font_family}}"; }
QFrame#pill { background: {{surface}}; border: 1px solid {{line_strong}}; border-radius: 16px;
              font-family: "{{font_family}}"; }
QLabel#handle { color: {{text_faint}}; font-size: 15px; }
QLabel#pillTitle { color: {{text}}; font-size: 13px; font-weight: 600; }
QLabel#pillUsage { color: {{text_faint}}; font-size: 12px; }
QLabel#pillHint { color: {{accent_strong}}; font-size: 12px; }

QPushButton#pick { background: {{bg_sunken}}; color: {{text_dim}}; border: 1px solid {{line_strong}};
                   border-radius: 10px; padding: 9px 16px; font-size: 14px; }
QPushButton#pick:hover { background: {{surface_2}}; border-color: {{accent}}; color: {{text}}; }
QPushButton#pick:pressed { background: {{bg_input}}; }

QLineEdit#ask { background: {{bg_input}}; border: 1px solid {{line_strong}}; border-radius: 10px;
                color: {{text}}; padding: 9px 13px; font-size: 14px;
                selection-background-color: {{accent}}; selection-color: {{on_accent}}; }
QLineEdit#ask:focus { border: 1px solid {{accent}}; background: {{surface}}; }

QPushButton#go { background: {{accent}}; color: {{on_accent}}; border: none; border-radius: 10px;
                 padding: 9px 24px; font-size: 14px; font-weight: 600; }
QPushButton#go:hover { background: {{accent_strong}}; }
QPushButton#go:pressed { background: {{accent_strong}}; }
QPushButton#go:disabled { background: {{bg_sunken}}; color: {{text_faint}}; }

QToolButton#tiny { color: {{text_faint}}; background: transparent; border: 1px solid transparent;
                   font-size: 13px; padding: 5px 8px; border-radius: 8px; }
QToolButton#tiny:hover { color: {{text}}; background: {{surface_2}}; }
QToolButton#tiny:pressed { background: {{bg_input}}; }
QToolButton#tiny:disabled { color: {{text_faint}}; background: transparent; }
QToolButton#tiny:checked { color: {{accent_strong}}; }   /* 置顶开着时亮蓝 */
QToolButton[role="accent"] { color: {{accent_strong}}; }  /* 复盘：主操作，蓝字 */
QToolButton[role="accent"]:hover { color: {{accent}}; background: {{accent_soft}}; }
QToolButton[role="danger"]:hover { color: {{err}}; background: {{err_soft}}; }  /* 清空：悬停泛红 */
QToolButton[role="recording"] { color: {{err}}; }        /* 录像中：红字提醒 */
QToolButton[starred="true"] { color: {{mark}}; }         /* 已收藏：金字 */

QLabel#status { color: {{text_faint}}; font-size: 12px; }
QLabel#rec { color: {{warn}}; font-size: 11px; }
QLabel#usage { color: {{text_faint}}; font-size: 11px; }
QLabel#thumb { border: 1px solid {{line_strong}}; border-radius: 8px; }

QTextBrowser#answer { background: {{bg_sunken}}; border: 1px solid {{line}}; border-radius: 10px;
                      color: {{text}}; padding: 13px 16px; font-size: 15px;
                      selection-background-color: {{accent_soft}}; }

QFrame#grip { background: {{line_strong}}; border-radius: 3px; }
QFrame#grip:hover { background: {{accent}}; }        /* 拖底边改答案区高度 */

QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 2px 4px 0; }
QScrollBar::handle:vertical { background: {{line_strong}}; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: {{text_faint}}; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QMenu { background: {{surface}}; border: 1px solid {{line_strong}}; border-radius: 10px; padding: 6px; }
QMenu::item { color: {{text_dim}}; background: transparent; padding: 7px 24px 7px 14px;
              border-radius: 6px; font-size: 13px; }
QMenu::item:selected { background: {{accent}}; color: {{on_accent}}; }
QMenu::item:disabled { color: {{text_faint}}; }
QMenu::separator { height: 1px; background: {{line}}; margin: 5px 8px; }

QToolTip { background: {{surface}}; color: {{text}}; border: 1px solid {{line}};
           padding: 4px 6px; font-size: 12px; }
"""

_PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")


def render_qss(tokens: dict[str, str] | None = None) -> str:
    """把令牌填进快捷栏模板；缺键用兜底，不会 KeyError。"""
    values = token_source.merged(
        tokens if tokens is not None
        else token_source.read_web_tokens(mood=BAR_MOOD))
    flat = {key[2:].replace("-", "_"): value for key, value in values.items()}
    flat["font_family"] = token_source.font_family(values)
    return _PLACEHOLDER.sub(lambda match: flat.get(match.group(1), ""), QSS_TEMPLATE)


THUMB_W, THUMB_H = 64, 40
BUTTON_W = 68                # 底部那排按钮统一宽度 —— 文字在「置顶 / 不置顶」之间变也不挪位

# ---- 固定几何（T3.5）----
# 每一行都钉死高度，窗口尺寸只由这些常量 + 答案面板高度算出来。
# 内容怎么长、状态文字多长，都不许再把窗口撑大或推按钮。
BAR_OUTER_X = 14             # 窗口左右留白（给阴影）
BAR_OUTER_TOP = 12           # 窗口顶部留白（给阴影）
CARD_PAD_X = 12
CARD_PAD_TOP = 10
CARD_PAD_BOTTOM = 10
CARD_GAP = 9                 # 卡片内各行间距
ROW_H = 40                   # 输入行（缩略图 40 高，整行跟着它）
BUTTON_H = 28                # 底部按钮行
STATUS_H = 22                # 状态行 —— 永远占着，长短只截断不换行
REC_H = 18                   # 录制信息行 —— 永远占着
USAGE_H = 16                 # 占用行
GRIP_H = 7                   # 答案面板底边的拖拽条
PILL_H = 44                  # 收起后的小条

# 状态机：所有界面显隐只认这一组名字（见 set_state）
STATE_IDLE = "idle"
STATE_THINKING = "thinking"
STATE_STREAMING = "streaming"
STATE_DONE = "done"
STATE_ERROR = "error"
STATE_HISTORY = "history"
_ANSWER_STATES = frozenset({STATE_THINKING, STATE_STREAMING, STATE_DONE,
                            STATE_ERROR, STATE_HISTORY})
_STATES = frozenset({STATE_IDLE, *_ANSWER_STATES})

MODE_LABELS = {
    "explain": "讲解（完整回答 + 思考题）",
    "guide": "引导（先给提示，再反问）",
    "quiz": "测验（出题 + 逐题批改）",
    "quick": "速答（短）",
}
MOVE_SLOP = 4                     # 拖动超过这么多像素才算「拖」，否则算「点」
_LINE_HEIGHT_PROPORTIONAL = 1     # QTextBlockFormat.ProportionalHeight（PySide6 里 int(枚举) 会报错）
_USAGE_TTL_SECONDS = 300.0        # 占用数字缓存多久：横栏每次露出来都触发，不缓存就是每次全盘 walk
_SCROLL_SLACK = 8                 # 滚动条离底部不足这么多像素 = 「正跟着看最新」
# 流式时多久重排一次 Markdown。太快会跟每个 token 抢 CPU；太慢看起来像卡住。
# 0.12 秒 ≈ 8 帧/秒：字一直在长，格式也一直是好的，不会先吐 `**` 再突然变粗体。
_STREAM_RENDER_SECONDS = 0.12


def _as_bool(value, default: bool) -> bool:
    """把设置文件里的值当开关读 —— `"false"` / `"0"` / `"关"` 是 False，不是 `bool(str)` 的 True。"""
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off", "关", "否")


def resolve_on_top(state: dict, default: bool) -> bool:
    """置顶状态：只有用户显式点过开关才认文件里的值。

    旧版把 `always_on_top` 直接写进 `界面设置.json`，于是某次误点留下的 false
    会永久压住 config 里的默认值（真踩过：默认置顶改完又被旧值盖回去）。
    现在用 `always_on_top_set` 区分「用户选择」和「历史残留」：
    - 有标记 ⇒ 读 `always_on_top`（字符串 "false" 也按 False 处理）；
    - 没标记 ⇒ 用 `default`，旧值一律忽略。
    """
    if not _as_bool(state.get("always_on_top_set"), False):
        return default
    return _as_bool(state.get("always_on_top"), default)


def _ask_char(tokens: dict[str, str] | None = None) -> QtGui.QTextCharFormat:
    """「我」那句话：淡蓝底、正文色 —— 只包住文字（不是整行一条）。

    用的是字符级背景，包多大取决于文字有多长；前后各塞一个空格当内边距。
    颜色来自令牌：控件要醒目，对话要柔和。
    """
    values = token_source.merged(
        tokens if tokens is not None
        else token_source.read_web_tokens(mood=BAR_MOOD))
    fmt = QtGui.QTextCharFormat()
    fmt.setBackground(style.color(values["--accent-soft"]))
    fmt.setForeground(style.color(values["--text"]))
    return fmt


def _gap_block() -> QtGui.QTextBlockFormat:
    """空行（你的话和 AI 的回答之间隔开一点），顺带定 165% 行高 —— 对话区排版统一。

    上下留白 4px：对话内容要「呼吸感」，宁可窗口高一点也别挤成一团。
    """
    fmt = QtGui.QTextBlockFormat()
    fmt.setTopMargin(4)
    fmt.setBottomMargin(4)
    fmt.setLineHeight(165.0, _LINE_HEIGHT_PROPORTIONAL)
    return fmt


def _answer_char(tokens: dict[str, str] | None = None) -> QtGui.QTextCharFormat:
    """AI 的回答：正文色（别继承「我」那块的字色）。"""
    values = token_source.merged(
        tokens if tokens is not None
        else token_source.read_web_tokens(mood=BAR_MOOD))
    fmt = QtGui.QTextCharFormat()
    fmt.setForeground(style.color(values["--text"]))
    return fmt


def _markdown_bold_for_qt(text: str) -> str:
    """把 `**加粗**` 换成 Qt 认的行内 `<b>`，但跳过 ``` 代码围栏。

    Qt 的 Markdown 解析器对「**（中文括号）**」这种边界会漏解析，
    把 `**` 原样留在界面上；换行内 HTML 能稳定加粗。代码围栏里的
    `a ** b` / `**kwargs` 不能动，所以按围栏切开只处理正文段。
    """
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"\*\*([^*\n]+?)\*\*", r"<b>\1</b>", parts[i])
    return "".join(parts)


def _thumb(pixmap: QtGui.QPixmap, width: int, height: int) -> QtGui.QPixmap:
    """把截的那块缩成圆角小图（按原比例，居中留白，不裁内容）。"""
    if pixmap is None or pixmap.isNull():
        return QtGui.QPixmap(width, height)          # 空图给空白，别炸在 toImage()
    box_w, box_h = width * 2, height * 2
    image = pixmap.toImage()
    image.setDevicePixelRatio(1.0)
    image = image.scaled(box_w, box_h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    image.setDevicePixelRatio(1.0)
    out = QtGui.QPixmap(box_w, box_h)
    out.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(out)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    path = QtGui.QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(box_w), float(box_h), 12.0, 12.0)
    painter.setClipPath(path)
    painter.drawImage((box_w - image.width()) // 2, (box_h - image.height()) // 2, image)
    painter.end()
    out.setDevicePixelRatio(2.0)
    return out
