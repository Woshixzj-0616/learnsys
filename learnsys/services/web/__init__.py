"""联网能力：搜索、抓网页、出网安检。

模块分工：
- `guard`   —— 这个地址能不能连（SSRF 判据，唯一落点）；
- `fetch`   —— 取字节（总预算连接、读取上限、兜底）；
- `extract` —— HTML → 正文（隐藏节点、数字保留）；
- `search`  —— DeepSeek 主源 + Bing 兜底 + 去重。
"""
from __future__ import annotations

from .fetch import FetchError, fetch as fetch_page
from .guard import Blocked, blocked_reason, check
from .search import web_search

__all__ = ["Blocked", "FetchError", "blocked_reason", "check", "fetch_page",
           "web_search"]
