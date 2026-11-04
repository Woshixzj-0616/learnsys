"""豆包：没有明文导出，只有 IndexedDB/LevelDB 二进制。

本适配器只返回「缺失」记录，不读取、不猜测、不逆向。
"""
from __future__ import annotations

from ..model import Source

MISSING_REASON = "仅有 IndexedDB/LevelDB 二进制，无明文导出"


def collect(cutoff_ts: float) -> dict:
    return {"files": 0, "sessions": [], "skipped": 0, "errors": 0,
            "missing": MISSING_REASON}


SOURCE = Source("doubao", "豆包", "H", collect, missing_reason=MISSING_REASON)
