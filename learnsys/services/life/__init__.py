"""生活域：订阅卡片生成与调度。

对外只暴露这些名字；业务规则在 `cards.py`，线程在 `scheduler.py`。
"""
from __future__ import annotations

from .art import (import_works, parse_import, safe_image_path,
                  validate_work)
from .cards import (KIND_LABELS, LifeNotReady, LifeUnsupported, MAX_TEXT,
                    PROMPT_VERSION, SUPPORTED_KINDS, generate, supported)
from .items import change_status, reminder_lines, summary, validate
from .scheduler import ensure_started, shutdown, tick

__all__ = ["KIND_LABELS", "LifeNotReady", "LifeUnsupported", "MAX_TEXT",
           "PROMPT_VERSION", "SUPPORTED_KINDS", "generate", "supported",
           "change_status", "reminder_lines", "summary", "validate",
           "import_works", "parse_import", "safe_image_path", "validate_work",
           "ensure_started", "shutdown", "tick"]
