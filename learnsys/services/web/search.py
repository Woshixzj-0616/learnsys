"""联网搜索：DeepSeek Search 主源 + Bing 直连兜底。

抄智能旅行的「多源 + 降级 + 去重重排」思路，但只留两条源、串行兜底（工作台是单人低频，
不值得为 0.3 秒并发再多养一层调度）：
- 主源有结果就不再跑兜底；主源失败 / 0 条才跑 Bing；
- 结果统一成 {title,url,snippet,date,engine}；同 URL 去重、同域最多 2 条、滤掉二进制文档；
- 10 分钟进程内缓存（不落库）：同一问题连问两次不重复出网。
"""
from __future__ import annotations

import base64
import html as html_lib
import json
import re
import threading
import time
import urllib.parse
import urllib.request

from learnsys.services.web import extract, fetch, guard

DEEPSEEK_SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
BING_SEARCH_URL = "https://cn.bing.com/search?q="
TIMEOUT = 8.0
MAX_PER_DOMAIN = 2
CACHE_TTL = 600.0
_BINARY_DOCS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                ".zip", ".rar", ".7z", ".mp3", ".mp4", ".wav", ".apk", ".exe")

_BING_BLOCK = re.compile(r'<li class="b_algo".*?(?=<li class="b_algo"|</ol>)', re.S)
_BING_JUMP = re.compile(r"[?&]u=a1([A-Za-z0-9_\-]+)")

_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _deepseek_key() -> tuple[str, str]:
    try:
        from learnsys.llm.config import load_config
        cfg = load_config()
        return (str(getattr(cfg, "auth_token", "") or "").strip(),
                str(getattr(cfg, "base_url", "") or "").lower())
    except Exception:
        return "", ""


def _deepseek(query: str, count: int) -> list[dict]:
    token, base = _deepseek_key()
    if not token or "deepseek.com" not in base:
        return []
    payload = json.dumps({"query": query[:128], "count": min(count, 10),
                          "need_content": False}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_SEARCH_URL, data=payload,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if getattr(resp, "status", 200) != 200:
                return []
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return []
    out = []
    for item in (data.get("results") or []):
        url = str(item.get("url") or "").strip()
        if not _usable(url):
            continue
        snippet = str(item.get("snippet") or item.get("summary") or "").strip()
        out.append({
            "title": str(item.get("title") or "").strip()[:120],
            "url": url,
            "snippet": snippet[:300],
            "date": str(item.get("date") or "")[:10],
            "engine": "deepseek",
        })
    return out


def unwrap(url: str) -> str:
    """Bing 跳转链（…/ck/a?…&u=a1<base64>）还原成真地址。"""
    match = _BING_JUMP.search(url or "")
    if not match:
        return url
    raw = match.group(1).replace("-", "+").replace("_", "/")
    raw += "=" * (-len(raw) % 4)
    try:
        return base64.b64decode(raw).decode("utf-8", "ignore") or url
    except Exception:
        return url


def _bing(query: str, count: int) -> list[dict]:
    try:
        raw, ctype, charset, _final = fetch.get_raw(
            BING_SEARCH_URL + urllib.parse.quote(query), timeout=TIMEOUT)
        page = fetch.decode(raw, charset)
    except Exception:
        return []
    out = []
    for block in _BING_BLOCK.findall(page):
        match = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not match:
            continue
        url = unwrap(html_lib.unescape(match.group(1)))
        if not _usable(url):
            continue
        snip = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        out.append({
            "title": extract.text_of(match.group(2))[:120],
            "url": url,
            "snippet": extract.text_of(snip.group(1))[:300] if snip else "",
            "date": "",
            "engine": "bing",
        })
        if len(out) >= count:
            break
    return out


def _usable(url: str) -> bool:
    if not str(url or "").lower().startswith(("http://", "https://")):
        return False
    if guard.blocked_reason(url):
        return False
    path = urllib.parse.urlparse(url).path.lower()
    return not path.endswith(_BINARY_DOCS)


def _norm_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path.rstrip("/") or "/"
    return host + path


def _dedupe(hits: list[dict], limit: int) -> list[dict]:
    seen: set[str] = set()
    per_domain: dict[str, int] = {}
    out = []
    for hit in hits:
        key = _norm_url(hit["url"])
        if key in seen:
            continue
        domain = (urllib.parse.urlsplit(hit["url"]).hostname or "").lower()
        if per_domain.get(domain, 0) >= MAX_PER_DOMAIN:
            continue
        seen.add(key)
        per_domain[domain] = per_domain.get(domain, 0) + 1
        out.append(hit)
        if len(out) >= limit:
            break
    return out


def web_search(query: str, count: int = 6) -> dict:
    """搜一次；返回 {query, results, source, cached}。两个源都空时 results=[]。"""
    text = " ".join(str(query or "").split())
    if not text:
        return {"query": "", "results": [], "source": "none", "cached": False}
    count = max(1, min(int(count or 6), 8))
    key = (text.lower(), count)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < CACHE_TTL:
            return dict(cached[1], cached=True)
    hits = _deepseek(text, count)
    source = "deepseek" if hits else ""
    if not hits:
        hits = _bing(text, count)
        source = "bing" if hits else "none"
    results = _dedupe(hits, count)
    payload = {"query": text, "results": results,
               "source": source if results else "none", "cached": False}
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > 200:                     # 粗暴上限：单人使用足够了
            oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])[:50]
            for old_key, _value in oldest:
                _CACHE.pop(old_key, None)
    return payload
