"""统一的内容去重键。

所有写记忆的入口（工具、自动抽取、导入器、面板）都只调这一个函数，
避免「精确相等 / 去空白 / 去标点」三套口径各自为政。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

MAX_KEY_CHARS = 500


def content_key(text: str) -> str:
    """把一句话压成去重键：NFKC、小写、去空白/标点/下划线，截 500 字。

    中文不会被去掉（`\\w` 在 Unicode 下包含汉字）；纯符号内容用哈希兜底，
    保证每条非空内容都有稳定、非空的键。
    """
    source = str(text or "")
    normalized = unicodedata.normalize("NFKC", source).lower()
    compact = re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)
    if compact:
        return compact[:MAX_KEY_CHARS]
    return "sha1:" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]
