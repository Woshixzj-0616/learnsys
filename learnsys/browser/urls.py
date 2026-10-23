"""URL 校验与域名判断：纯函数，API / Agent 工具 / 轮询共用这一份。

只放行 http/https；长度、userinfo、协议都是硬门槛。
"""
from __future__ import annotations

import re
import urllib.parse

MAX_URL_LENGTH = 2048
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SCHEME_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def normalize_url(raw: str) -> str:
    """校验并返回可打开的 URL；不合法抛 ValueError（中文原因）。"""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("网址是空的。")
    if len(text) > MAX_URL_LENGTH:
        raise ValueError(f"网址太长（上限 {MAX_URL_LENGTH} 字符）。")
    if any(ch.isspace() for ch in text):
        raise ValueError("网址里不能有空格。")
    if "://" not in text:
        # `javascript:...` / `file:...` / `C:\\x` 这类没有 `://` 的协议一律拒；
        # 只把「example.com」这种裸域名补成 https。
        if _SCHEME_LIKE.match(text):
            raise ValueError("只允许 http / https 网址。")
        text = "https://" + text
    parts = urllib.parse.urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("只允许 http / https 网址。")
    if not parts.netloc:
        raise ValueError("网址缺少域名。")
    if "@" in parts.netloc:
        raise ValueError("网址里不能带用户名密码（userinfo）。")
    try:
        host = parts.hostname
    except ValueError as exc:
        raise ValueError("网址格式不对。") from exc
    if not host:
        raise ValueError("网址缺少域名。")
    return text


def domain_of(url: str) -> str:
    """取小写域名；解析失败返回空串（调用方直接跳过）。"""
    try:
        host = urllib.parse.urlsplit(str(url or "")).hostname or ""
    except ValueError:
        return ""
    return host.lower().rstrip(".")


def is_loopback(domain: str) -> bool:
    value = str(domain or "").lower()
    return value in LOOPBACK_HOSTS or value.endswith(".localhost")


def is_excluded(domain: str, patterns) -> bool:
    """域名排除：命中本身或任意后缀（`example.com` 覆盖 `a.example.com`）。"""
    value = str(domain or "").lower().rstrip(".")
    if not value:
        return False
    for raw in patterns or []:
        pattern = str(raw or "").lower().strip().lstrip(".").rstrip(".")
        if not pattern:
            continue
        if value == pattern or value.endswith("." + pattern):
            return True
    return False
