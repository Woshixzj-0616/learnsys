"""工具确认策略：写操作 / 动系统固定确认，白名单外读本机文件才确认。"""
from __future__ import annotations

import pathlib

from .schemas import CONFIRM_TOOLS


def needs_confirm(name: str, args: dict | None = None, ctx=None) -> bool:
    if name in CONFIRM_TOOLS:
        return True
    if name != "read_local_file":
        return False
    raw = str((args or {}).get("path") or "").strip() if isinstance(args, dict) else ""
    from .local_files import is_allowed_path
    if is_allowed_path(raw):
        return False
    approved = {str(item).casefold() for item in getattr(ctx, "approved_paths", ())}
    keys = {raw.casefold()}
    try:
        keys.add(str(pathlib.Path(raw).expanduser().resolve()).casefold())
    except (OSError, ValueError):
        pass
    # 同一个文件确认过一次，后续分段读不再重复弹框。
    return not (keys & approved)
