"""抓网页：出网安检 + 总预算连接 + 读取上限 + 正文抽取 + 兜底。

移植自智能旅行 `services/fetch/http.py` 的关键判据（去掉了它给自建 SearXNG 的内部通道）：
- **总预算**：一次抓取总共 10 秒，不是每个解析地址各吃 10 秒；
- **读也有上限**：2MB + 8 秒，防止「隔一会儿吐一个字节」；
- **每一跳都过安检**：30x 跳到内网同样拦；
- 直连失败 / 正文太短 → DeepSeek Fetch 兜底（它用自己的索引抓，返回 Markdown）。
"""
from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.parse
import urllib.request
import zlib

from learnsys.services.web import extract, guard

TIMEOUT = 10.0
READ_SECONDS = 8.0
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
MIN_TEXT = 200

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain",
               "application/json", "application/xml", "text/xml", "text/markdown")


class FetchError(OSError):
    """抓取失败；`str(exc)` 是给模型看的中文原因。"""


def connect_within(address, timeout, source_address=None):
    """连上 (host, port)：所有解析地址共用一份预算，每个地址至少给 1 秒机会。"""
    host, port = address
    budget = float(timeout if isinstance(timeout, (int, float)) else TIMEOUT)
    deadline = time.monotonic() + max(0.5, budget)
    last = None
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    safe = [info for info in infos if not guard.ip_blocked(info[4][0])]
    if infos and not safe:
        raise guard.Blocked("这个地址解析到内网 / 本机（%s），不能从这里取"
                            % infos[0][4][0])
    infos = safe
    for index, (af, socktype, proto, _canon, sockaddr) in enumerate(infos):
        left = deadline - time.monotonic()
        if left <= 0:
            break
        share = min(left, max(1.0, left / max(1, len(infos) - index)))
        try:
            sock = socket.socket(af, socktype, proto)
        except OSError as exc:
            last = exc
            continue
        try:
            sock.settimeout(share)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
        except OSError as exc:
            last = exc
            sock.close()
            continue
        sock.settimeout(budget)
        return sock
    raise last or socket.timeout("连接超时")


def _guarded_connect(address, timeout, source_address=None):
    return connect_within(address, timeout, source_address)


class _BoundedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _guarded_connect


class _BoundedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _guarded_connect


class _BoundedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_BoundedHTTPConnection, req)


class _BoundedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_BoundedHTTPSConnection, req, context=self._context)


class _RedirectLimited(urllib.request.HTTPRedirectHandler):
    @property
    def max_redirections(self):
        return MAX_REDIRECTS


_OPENER = urllib.request.build_opener(
    _BoundedHTTPHandler(), _BoundedHTTPSHandler(), _RedirectLimited())


def decode(raw: bytes, charset: str = "") -> str:
    for enc in ([charset] if charset else []) + ["utf-8", "gb18030"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


def _sock_of(resp):
    try:
        return resp.fp.raw._sock
    except AttributeError:
        return None


def _inflate(raw: bytes, encoding: str) -> bytes:
    enc = str(encoding or "").strip().lower()
    if enc not in ("gzip", "x-gzip", "deflate"):
        return raw
    for wbits in ((31,) if enc != "deflate" else (15, -15)):
        try:
            stream = zlib.decompressobj(wbits)
            out = stream.decompress(raw, MAX_BYTES + 1)
        except zlib.error:
            continue
        if len(out) > MAX_BYTES or stream.unconsumed_tail:
            raise FetchError("这个页面解开压缩后超过 2MB，不读了")
        return out
    return raw


def _read_bounded(resp) -> bytes:
    deadline = time.monotonic() + READ_SECONDS
    sock = _sock_of(resp)
    read_one = getattr(resp, "read1", None) or resp.read
    body = bytearray()
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise FetchError(f"读这个页面超过 {int(READ_SECONDS)} 秒，断开了")
        if sock is not None:
            try:
                sock.settimeout(left)
            except OSError:
                sock = None
        chunk = read_one(65536)
        if not chunk:
            break
        body += chunk
        if len(body) > MAX_BYTES:
            raise FetchError("这个页面超过 2MB，不读了")
    headers = getattr(resp, "headers", None)
    encoding = headers.get("content-encoding") if hasattr(headers, "get") else ""
    return _inflate(bytes(body), encoding)


def get_raw(url: str, timeout: float = TIMEOUT):
    """取原始字节；返回 (raw, content_type, charset, final_url)。"""
    guard.check(url)
    req = urllib.request.Request(url, headers=HEADERS)
    with _OPENER.open(req, timeout=timeout) as resp:
        ctype = (resp.headers.get_content_type() or "").lower()
        if ctype and ctype not in _TEXT_TYPES:
            raise FetchError(f"这个地址不是网页（{ctype}），读不了")
        raw = _read_bounded(resp)
        return raw, ctype, (resp.headers.get_content_charset() or ""), resp.geturl()


def _deepseek_fetch(url: str, timeout: float = 15.0) -> str:
    """DeepSeek Fetch 兜底：只在直连失败/正文太短时用；没 key 就当没有。"""
    try:
        from learnsys.llm.config import load_config
        cfg = load_config()
        token = str(getattr(cfg, "auth_token", "") or "").strip()
        base = str(getattr(cfg, "base_url", "") or "").lower()
    except Exception:
        return ""
    if not token or "deepseek.com" not in base:
        return ""
    payload = json.dumps({"url": url}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/tools/fetch", data=payload,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return ""
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return ""
    return str(data.get("content") or "").strip()


def _is_html(ctype: str, url: str) -> bool:
    if ctype in ("text/html", "application/xhtml+xml"):
        return True
    if ctype:
        return False
    return str(url or "").lower().endswith((".html", ".htm", "/"))


def fetch(url: str, max_chars: int = 8000) -> dict:
    """抓一个网页 → {url, final_url, title, text, via, chars}。失败抛 FetchError。"""
    text = str(url or "").strip()
    if not text:
        raise FetchError("没给网址")
    if not text.lower().startswith(("http://", "https://")):
        raise FetchError("只支持 http / https 网址")
    max_chars = max(1000, min(int(max_chars or 8000), 12000))
    via = "direct"
    final_url = text
    title = ""
    body = ""
    direct_error = ""
    try:
        raw, ctype, charset, final_url = get_raw(text)
        decoded = decode(raw, charset)
        title = extract.title_of(decoded)
        body = (extract.extract_text(decoded) if _is_html(ctype, final_url)
                else decoded.strip())
    except guard.Blocked:
        raise
    except Exception as exc:
        direct_error = str(exc)
        body = ""
    if len(body) < MIN_TEXT:
        fallback = _deepseek_fetch(text)
        if len(fallback) >= len(body):
            body, via, final_url = fallback, "deepseek", text
    if not body:
        raise FetchError("这个页面没取到正文" + (f"（{direct_error}）" if direct_error else ""))
    return {
        "url": text,
        "final_url": final_url,
        "title": title,
        "text": extract.clip_text(body, max_chars),
        "via": via,
        "chars": len(body),
    }
