"""读取简报设置：默认值 + 类型/时间格式清洗。"""
from __future__ import annotations

import re

from learnsys import config

BRIEFING_DEFAULTS = {"enabled": True, "generate_at": "07:30"}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def briefing_settings() -> dict:
    """老设置文件没有 briefing 块时也能用默认。"""
    raw = config.load_settings().get("briefing")
    raw = raw if isinstance(raw, dict) else {}
    value = raw.get("enabled")
    if isinstance(value, bool):
        enabled = value
    elif value is None or str(value).strip() == "":
        enabled = bool(BRIEFING_DEFAULTS["enabled"])
    else:
        enabled = str(value).strip().lower() not in ("0", "false", "no", "off", "关", "否")
    when = str(raw.get("generate_at") or BRIEFING_DEFAULTS["generate_at"]).strip()
    if not _TIME.match(when):
        when = BRIEFING_DEFAULTS["generate_at"]
    return {"enabled": enabled, "generate_at": when}
