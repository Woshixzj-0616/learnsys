"""工作台浏览器：独立 profile 的 Edge/Chrome + 本机 CDP 只读轮询。

这里只做三件事：启动/复用/关闭进程、读标签页、把 URL/标题/域名落库。
不开放 `Runtime.evaluate` / `Page.navigate`，也从不碰用户的默认浏览器 profile。
"""
from __future__ import annotations

from .manager import BrowserManager, get_manager

__all__ = ["BrowserManager", "get_manager"]
