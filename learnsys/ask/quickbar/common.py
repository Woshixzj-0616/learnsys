"""快捷栏的样式、几何常量、状态名与小工具函数（改样式先看这里）。"""
from __future__ import annotations

import re

from PySide6 import QtCore, QtGui


# 设计规范（改样式先看这里，别一处一处试）：
#   底色  卡片 #1b1e23 ｜ 输入 #23262b ｜ 答案区 #15171a（一层比一层深，视线自然往下走）
#   强调  蓝 #4d8bff（问 / 复盘 / 输入焦点 / 菜单选中）
#   语义  清空=危险（悬停泛红）｜ 收藏=金色（已收藏★）｜ 置顶开=蓝字
#   圆角  卡片 14 ｜ 输入/按钮/答案 10 ｜ 小按钮 8 ｜ 菜单 10
#   字号  答案 15 ｜ 输入/主按钮 14 ｜ 小按钮 13 ｜ 状态 12 ｜ 占用/记录 11
#   ⚠️ 按钮宽度 BUTTON_W 恒定、位置不动 —— 美化不许破坏肌肉记忆（见按钮行注释）
QSS = """
QFrame#bar { background: #1b1e23; border: 1px solid #33383f; border-radius: 14px;
             font-family: "Microsoft YaHei UI"; }
QFrame#pill { background: #1b1e23; border: 1px solid #33383f; border-radius: 16px;
              font-family: "Microsoft YaHei UI"; }
QLabel#handle { color: #6f757e; font-size: 15px; }
QLabel#pillTitle { color: #e6e9ec; font-size: 13px; font-weight: 600; }
QLabel#pillUsage { color: #868c95; font-size: 12px; }
QLabel#pillHint { color: #5aaaff; font-size: 12px; }

QPushButton#pick { background: #262b31; color: #d7dbe0; border: 1px solid #3a3f46;
                   border-radius: 10px; padding: 9px 16px; font-size: 14px; }
QPushButton#pick:hover { background: #303743; border-color: #4d8bff; color: #ffffff; }
QPushButton#pick:pressed { background: #242a31; }

QLineEdit#ask { background: #23262b; border: 1px solid #3a3f46; border-radius: 10px;
                color: #f1f3f4; padding: 9px 13px; font-size: 14px;
                selection-background-color: #2f6bed; }
QLineEdit#ask:focus { border: 1px solid #4d8bff; background: #25282d; }

QPushButton#go { background: #2f6bed; color: #ffffff; border: none; border-radius: 10px;
                 padding: 9px 24px; font-size: 14px; font-weight: 600; }
QPushButton#go:hover { background: #3d78f2; }
QPushButton#go:pressed { background: #2a5fd0; }
QPushButton#go:disabled { background: #33383f; color: #7e848c; }

QToolButton#tiny { color: #9aa0a6; background: transparent; border: 1px solid transparent;
                   font-size: 13px; padding: 5px 8px; border-radius: 8px; }
QToolButton#tiny:hover { color: #ffffff; background: #2c3037; }
QToolButton#tiny:pressed { background: #262a30; }
QToolButton#tiny:disabled { color: #474c53; background: transparent; }
QToolButton#tiny:checked { color: #5aaaff; }          /* 置顶开着时亮蓝 */
QToolButton[role="accent"] { color: #6ea8ff; }         /* 复盘：主操作，蓝字 */
QToolButton[role="accent"]:hover { color: #a8ccff; background: #243043; }
QToolButton[role="danger"]:hover { color: #ff8177; background: #34262a; }  /* 清空：悬停泛红 */
QToolButton[role="recording"] { color: #ff8177; }      /* 录像中：红字提醒 */
QToolButton[starred="true"] { color: #f5b74e; }        /* 已收藏：金字 */

QLabel#status { color: #98a1ab; font-size: 12px; }
QLabel#rec { color: #ffb454; font-size: 11px; }
QLabel#usage { color: #6f757e; font-size: 11px; }
QLabel#thumb { border: 1px solid #3a3f46; border-radius: 8px; }

QTextBrowser#answer { background: #171c23; border: 1px solid #283039; border-radius: 10px;
                      color: #dfe6ee; padding: 13px 16px; font-size: 15px;
                      selection-background-color: #35618f; }

QFrame#grip { background: #2a2f36; border-radius: 3px; }
QFrame#grip:hover { background: #4d8bff; }           /* 拖底边改答案区高度 */

QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 2px 4px 0; }
QScrollBar::handle:vertical { background: #3a4048; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4a525c; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QMenu { background: #202329; border: 1px solid #33383f; border-radius: 10px; padding: 6px; }
QMenu::item { color: #d7dbe0; background: transparent; padding: 7px 24px 7px 14px;
              border-radius: 6px; font-size: 13px; }
QMenu::item:selected { background: #2f6bed; color: #ffffff; }
QMenu::item:disabled { color: #6b7178; }
QMenu::separator { height: 1px; background: #33383f; margin: 5px 8px; }

QToolTip { background: #202329; color: #d7dbe0; border: 1px solid #33383f;
           padding: 4px 6px; font-size: 12px; }
"""

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


def _ask_char() -> QtGui.QTextCharFormat:
    """「我」那句话：雾蓝底、近白的字 —— 只包住文字（不是整行一条）。

    用的是字符级背景，包多大取决于文字有多长；前后各塞一个空格当内边距。
    颜色特意比按钮的强调蓝灰一档：控件要醒目，对话要柔和（「自然清新」的出处）。
    """
    fmt = QtGui.QTextCharFormat()
    fmt.setBackground(QtGui.QColor("#35618f"))
    fmt.setForeground(QtGui.QColor("#f0f5fc"))
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


def _answer_char() -> QtGui.QTextCharFormat:
    """AI 的回答：柔和的冷白（别继承「我」那块的字色，也别纯白刺眼）。"""
    fmt = QtGui.QTextCharFormat()
    fmt.setForeground(QtGui.QColor("#dce4ee"))
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
