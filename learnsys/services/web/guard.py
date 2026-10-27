"""出网安检：这个地址能不能取。

唯一判据、两处落点（抄智能旅行 `services/fetch/url_guard.py`，去掉内部搜索后端那一支）：
1. 取之前（`fetch.get_raw`）：协议 + 主机名 —— 一眼假的地址连 DNS 都不做；
2. 连之前（`fetch.connect_within`）：**解析出来的每个地址**都要过 —— 域名解析成内网、
   30x 跳到内网、DNS 换脸，全在「真正连上的那一刻」收口。

只判「能不能连」：不判内容、不判好坏。
"""
from __future__ import annotations

import ipaddress
import urllib.parse

#: 公网抓取只走这两个口。
ALLOWED_PORTS = (80, 443)

BLOCKED_V4 = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8",
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "100.64.0.0/10",                                       # 阿里云元数据 100.100.100.200
    "127.0.0.0/8",
    "169.254.0.0/16",                                      # AWS/GCP/阿里云元数据
    "192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4", "255.255.255.255/32",
))
BLOCKED_V6 = tuple(ipaddress.ip_network(n) for n in (
    "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8", "2001:db8::/32",
))

BLOCKED_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost",
                 "ip6-loopback", "metadata", "metadata.google.internal",
                 "instance-data")
BLOCKED_SUFFIX = (".localhost", ".local", ".internal", ".home.arpa", ".lan")


class Blocked(OSError):
    """地址过不了安检；`str(exc)` 是一句中文人话（给模型看）。"""


def _ascii_name(host: str) -> str:
    """Unicode / 全角主机名归一到套接字真正会解析的那个名字（IDNA 内含 NFKC）。"""
    if not host:
        return host
    try:
        return host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return host


def host_port(url: str) -> tuple[str, int]:
    """`(小写主机名, 端口)`；读不出来给 `("", 0)`。只有这一处认 URL 的地址部分。"""
    try:
        parts = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return "", 0
    host = _ascii_name((parts.hostname or "").strip().lower()).rstrip(".")
    try:
        port = int(parts.port or 0)
    except ValueError:
        return "", 0
    if not port:
        port = 443 if (parts.scheme or "").lower() == "https" else 80
    return host, port


def port_allowed(port) -> bool:
    try:
        return int(port or 0) in ALLOWED_PORTS
    except (TypeError, ValueError):
        return False


def ip_blocked(ip_text: str) -> bool:
    """IP 字面量能不能连；认不出来的（域名）一律放行，交给解析后那一层。"""
    try:
        ip = ipaddress.ip_address(str(ip_text or "").strip().strip("[]"))
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    nets = BLOCKED_V6 if ip.version == 6 else BLOCKED_V4
    return any(ip in net for net in nets)


def blocked_reason(url: str) -> str:
    """不能取就回一句中文原因，能取回空串。"""
    text = str(url or "").strip()
    if not text:
        return "没给地址"
    try:
        scheme = (urllib.parse.urlsplit(text).scheme or "").lower()
    except ValueError:
        return "这个地址读不出来"
    if scheme not in ("http", "https"):
        return "只取 http / https 的页面"
    try:
        if urllib.parse.urlsplit(text).username:
            return "地址里带账号密码，不能从这里取"
    except ValueError:
        return "这个地址读不出来"
    host, port = host_port(text)
    if not host:
        return "这个地址里没有主机名"
    # 先判「是不是自己人」再判端口：127.0.0.1:8765 应该回「本机地址」，不是「端口不对」。
    if host in BLOCKED_NAMES or host.endswith(BLOCKED_SUFFIX):
        return "这是本机 / 内网的名字，不能从这里取"
    if ip_blocked(host):
        return "这是本机 / 内网 / 元数据地址，不能从这里取"
    if not port_allowed(port):
        return "只取 80 / 443 两个口上的页面"
    return ""


def check(url: str) -> str:
    """过安检：拦下就抛 `Blocked`，放行原样返回 url。"""
    reason = blocked_reason(url)
    if reason:
        raise Blocked(reason)
    return url
