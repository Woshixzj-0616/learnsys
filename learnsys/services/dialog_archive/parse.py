"""解析封存档案里的消息块（只依赖标准库与渲染常量，避免循环导入）。"""
from __future__ import annotations

import pathlib
import re

from .render import BODY_START

_MESSAGE = re.compile(
    r"<!-- learnsys:anchor (archive:[^ ]+/m(\d{4})) -->\n"
    r"#### m\d{4} · (用户|助手) · ([^\n]*)\n\n"
    r"(`{3,})text\n(.*?)\n\5\n", re.DOTALL)


def iter_archive_messages(path) -> list[dict]:
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    start = text.find(BODY_START)
    if start >= 0:
        text = text[start:]
    rows = []
    for match in _MESSAGE.finditer(text):
        rows.append({"anchor": match.group(1), "role": match.group(3),
                     "at": match.group(4), "text": match.group(6)})
    return rows
