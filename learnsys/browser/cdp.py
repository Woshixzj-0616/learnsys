"""CDP 的 HTTP 端点客户端：只读 `/json/list`，外加新标签 / 关标签。

**不实现 WebSocket 命令通道**：模型永远拿不到端口，也没有 `Runtime.evaluate` /
`Page.navigate` 的入口。所有请求 2 秒超时，异常交给调用方决定怎么降级。
"""
from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request


class CdpError(RuntimeError):
    """CDP 端点不可用 / 回了不是 JSON 的内容。"""


def read_devtools_port(profile: pathlib.Path) -> int | None:
    """Chromium 把随机调试端口写进 profile 的 `DevToolsActivePort`（首行）。"""
    path = pathlib.Path(profile) / "DevToolsActivePort"
    try:
        first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
        port = int(first)
    except (OSError, IndexError, ValueError):
        return None
    return port if 0 < port < 65536 else None


def _request(port: int, path: str, *, method: str = "GET",
             timeout: float = 2.0) -> str:
    url = f"http://127.0.0.1:{int(port)}{path}"
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CdpError(f"连不上浏览器调试端口：{exc}") from exc


def get_json(port: int, path: str, *, method: str = "GET",
             timeout: float = 2.0):
    raw = _request(port, path, method=method, timeout=timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CdpError("浏览器调试端口返回的不是 JSON") from exc


def parse_pages(payload) -> list[dict]:
    """`/json/list` 响应 → 只留 `type=page` 的 `id/url/title`；坏条目直接跳过。"""
    if not isinstance(payload, list):
        return []
    pages: list[dict] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("type") != "page":
            continue
        tab_id = str(item.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        if not tab_id or not url:
            continue
        pages.append({"id": tab_id, "url": url,
                      "title": str(item.get("title") or "")})
    return pages


def list_pages(port: int, *, timeout: float = 2.0) -> list[dict]:
    return parse_pages(get_json(port, "/json/list", timeout=timeout))


def version_ok(port: int, *, timeout: float = 1.0) -> bool:
    """端口活着且真的是 Chromium 调试端点。"""
    try:
        data = get_json(port, "/json/version", timeout=timeout)
    except CdpError:
        return False
    return isinstance(data, dict) and bool(data.get("Browser"))


def new_tab(port: int, url: str, *, timeout: float = 2.0) -> dict:
    """新版 Chromium 要求 `PUT /json/new?...`；失败抛 CdpError 由调用方回退。"""
    quoted = urllib.parse.quote(str(url), safe="")
    data = get_json(port, f"/json/new?{quoted}", method="PUT", timeout=timeout)
    if not isinstance(data, dict):
        raise CdpError("新标签页返回的不是 JSON 对象")
    return data


def close_tab(port: int, tab_id: str, *, timeout: float = 2.0) -> bool:
    quoted = urllib.parse.quote(str(tab_id), safe="")
    try:
        _request(port, f"/json/close/{quoted}", timeout=timeout)
    except CdpError:
        return False
    return True
