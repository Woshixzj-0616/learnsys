"""Qt → 已打开 Web 工作台的待跳转队列（B1 深链桥）。

只保存「最新一次跳转请求」，Web 壳按 seq 增量应用。
路由解析仍只在 Web 壳里做一份；Qt 只负责说「去这个 hash」。

- `server`：服务进程随机 id。后台重启后 Web 侧据此把本地 seq 归零。
- `seq`：单调递增；Web 只应用比本地大的序号。
- `ttl`：点击后窗口没被叫起来时，不让它在很久之后突然乱跳。
"""
from __future__ import annotations

import secrets
import threading
import time

MAX_HREF = 512
TTL_SECONDS = 30.0


def clean_href(value: object) -> str:
    """只接受页内深链 `#/...`；其余一律 ValueError（接口转 400）。"""
    text = str(value or "").strip()
    if not text.startswith("#/"):
        raise ValueError("深链必须以 #/ 开头")
    if text.startswith("#//"):
        raise ValueError("深链格式不对")
    if len(text) > MAX_HREF:
        raise ValueError("深链太长")
    if any(ord(char) < 32 for char in text):
        raise ValueError("深链里有控制字符")
    return text


class NavBridge:
    """进程内状态；锁只保护「写 seq + 读快照」这一小段。"""

    def __init__(self, ttl: float = TTL_SECONDS, clock=time.monotonic):
        self._lock = threading.Lock()
        self._server = secrets.token_hex(4)
        self._seq = 0
        self._href = ""
        self._at: float | None = None
        self._ttl = float(ttl)
        self._clock = clock

    @property
    def server(self) -> str:
        return self._server

    def set(self, href: object) -> int:
        """记下一条待跳转；返回新 seq。格式不对抛 ValueError。"""
        text = clean_href(href)
        with self._lock:
            self._seq += 1
            self._href = text
            self._at = self._clock()
            return self._seq

    def snapshot(self) -> dict:
        """最新一条；过期或从未写入时 href 为空。"""
        with self._lock:
            fresh = bool(self._href) and self._at is not None \
                and self._clock() - self._at <= self._ttl
            return {
                "server": self._server,
                "seq": self._seq,
                "href": self._href if fresh else "",
            }
