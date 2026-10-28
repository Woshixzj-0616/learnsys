"""抓取内置 RSS/Atom，解析成统一的 RawItem。

不引第三方依赖：fetch 仍走 `services/web` 的 SSRF 防护与 2MB/10s 上限。
"""
from __future__ import annotations

import datetime as dt
import email.utils
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

from learnsys.services.web import extract, fetch_page
from learnsys.services.web.fetch import FetchError, decode, get_raw
from learnsys.services.web.guard import Blocked

from .sources import SOURCES, RawItem, Source


def _local(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1].lower()


def _parse_time(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    moment = None
    try:
        moment = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        moment = None
    if moment is None:
        for candidate in (text.replace("Z", "+00:00"), text[:19]):
            try:
                moment = dt.datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue
    if moment is None:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.strftime("%Y-%m-%d %H:%M")


def _text(node) -> str:
    return " ".join((node.text or "").split()) if node is not None else ""


def _link_of(node) -> str:
    fallback = ""
    for child in list(node):
        if _local(child.tag) != "link":
            continue
        href = str(child.get("href") or child.text or "").strip()
        if not href:
            continue
        rel = str(child.get("rel") or "alternate").lower()
        if rel == "alternate":
            return href
        fallback = fallback or href
    if fallback:
        return fallback
    for child in list(node):
        if _local(child.tag) == "guid" and str(child.get("isPermaLink") or "true").lower() != "false":
            return str(child.text or "").strip()
    return ""


def parse_feed(raw: bytes, source: Source) -> list[RawItem]:
    """RSS 2.0 / Atom → RawItem；坏条目跳过，不让一个源拖垮整批。"""
    if b"<!ENTITY" in raw[:8192]:
        raise ValueError("源里带 ENTITY 声明，跳过")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError):
        # ElementTree 不认 GB2312/GBK 这类多字节声明：先解码成 str，
        # 去掉 XML 声明再解析（声明里的 encoding 对 str 没意义）。
        text = decode(raw)
        text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)
        if "<!ENTITY" in text[:8192]:
            raise ValueError("源里带 ENTITY 声明，跳过")
        root = ET.fromstring(text)

    items: list[RawItem] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        fields = {}
        for child in list(node):
            fields.setdefault(_local(child.tag), child)
        title = extract.strip_tags(_text(fields.get("title"))).strip()
        if not title:
            continue
        link = _link_of(node)
        if not link:
            continue
        link = urllib.parse.urljoin(source.url, link)
        if urllib.parse.urlsplit(link).scheme.lower() not in ("http", "https"):
            continue
        body_node = None
        for key in ("encoded", "description", "summary", "content"):
            body_node = fields.get(key)
            if body_node is not None:
                break
        body_html = (ET.tostring(body_node, encoding="unicode")
                     if body_node is not None else "")
        summary = extract.strip_tags(html.unescape(body_html)).strip()
        summary = re.sub(r"\s+", " ", summary)[:500]
        raw_time = ""
        for key in ("pubdate", "published", "updated", "date"):
            if fields.get(key) is not None:
                raw_time = _text(fields[key])
                break
        published = _parse_time(raw_time)
        items.append(RawItem(
            source_id=source.id, source_name=source.name,
            source_weight=source.weight, category_hint=source.category,
            title=title[:300], url=link, summary=summary,
            published_at=published or dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            meta={"time_estimated": not bool(published), "feed": source.url},
        ))
    return items


def fetch_source(source: Source, *, timeout: float = 10.0) -> tuple[list[RawItem], str]:
    try:
        raw, _ctype, _charset, _final = get_raw(source.url, timeout=timeout)
        items = parse_feed(raw, source)
        return items, "" if items else "没有解析到条目"
    except Blocked as exc:
        return [], f"被拦截：{exc}"
    except FetchError as exc:
        return [], f"抓取失败：{exc}"
    except Exception as exc:
        return [], f"解析失败：{exc}"


def fetch_bodies(items: list[dict], *, min_chars: int = 80,
                 max_chars: int = 3000, workers: int = 4) -> int:
    """只给 feed 摘要太短的入选条目补正文；失败就保留原摘要。"""
    targets = [item for item in items
               if len(str(item.get("summary") or "").strip()) < min_chars]
    if not targets:
        return 0
    def one(item: dict) -> str:
        try:
            page = fetch_page(str(item.get("url") or ""), max_chars=max_chars)
            return str(page.get("text") or "").strip()
        except Exception:
            return ""
    filled = 0
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers or 4), 8))) as pool:
        for item, text in zip(targets, pool.map(one, targets)):
            if text:
                item["summary"] = text[:500]
                item.setdefault("meta", {})["body_fetched"] = True
                filled += 1
    return filled


def fetch_all(*, sources=SOURCES, workers: int = 4,
              timeout: float = 10.0) -> tuple[list[RawItem], dict]:
    """并发抓源；单源失败只记 stats，不影响其他源。"""
    items: list[RawItem] = []
    stats: dict[str, dict] = {}
    workers = max(1, min(int(workers or 4), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(fetch_source, source, timeout=timeout): source
                for source in sources}
        for job in as_completed(jobs):
            source = jobs[job]
            try:
                got, error = job.result()
            except Exception as exc:  # 兜底：线程里抛出的非预期错误
                got, error = [], f"抓取线程异常：{exc}"
            items.extend(got)
            latest = max((item.published_at for item in got), default="")
            stats[source.id] = {
                "name": source.name, "url": source.url,
                "status": "ok" if got else "error",
                "count": len(got), "latest": latest,
                "error": error,
            }
    return items, stats
