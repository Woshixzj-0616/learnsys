"""Qt 深链怎么落地：已有 Web 窗口写队列，没有就新开窗口。

路由解析不在 Qt 复制一份：这里只把 href 变成完整 URL / `#/...`，
真正的页面跳转由 Web 壳按服务端队列执行（见 `server/nav_bridge.py`）。
"""
from __future__ import annotations

import json
import urllib.request


def hash_target(href: object) -> str:
    """页内深链转成 `#/...`；外部 http(s) 或根路径返回空串（不走队列）。"""
    text = str(href or "#/today").strip() or "#/today"
    if text.startswith(("http://", "https://", "/")):
        return ""
    if text.startswith("#/"):
        return text
    if text.startswith("#"):
        return "#/" + text[1:]
    return "#/" + text


def workbench_url(port: int, href: object) -> str:
    """打开新窗口时用的完整地址（带 hash 直接落在目标页）。"""
    text = str(href or "#/today").strip() or "#/today"
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("/"):
        return f"http://127.0.0.1:{int(port)}{text}"
    target = hash_target(text)
    return f"http://127.0.0.1:{int(port)}/{target}"


def post_navigate(port: int, href: str, timeout: float = 1.5) -> bool:
    """把目标写进后台待跳转队列；失败返回 False，不抛异常打断点击流程。"""
    base = f"http://127.0.0.1:{int(port)}"
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=timeout) as response:
            token = str(json.loads(response.read().decode("utf-8", "replace"))
                        .get("token") or "")
        body = json.dumps({"href": href}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{base}/api/ui/navigate",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json",
                     "X-Learnsys-Token": token},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False
