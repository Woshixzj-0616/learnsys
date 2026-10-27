"""兼容门面：旧的 `learnsys.ask.bar` 导入路径不变。

真正实现按职责拆在 `learnsys/ask/quickbar/`；这里只做转发，不要在这里写逻辑。
"""
from .quickbar import *  # noqa: F401,F403
from .quickbar import (AskBar, STATE_DONE, STATE_ERROR, STATE_HISTORY,
                       STATE_IDLE, STATE_STREAMING, STATE_THINKING, _AnswerGrip,
                       _AskWorker, _UsageWorker, _answer_char, _as_bool, _ask_char,
                       _gap_block, _markdown_bold_for_qt, _thumb, render_qss)

__all__ = [name for name in dir() if not name.startswith("__")]
