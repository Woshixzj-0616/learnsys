"""网页 → 正文。

判据抄智能旅行 `services/fetch/extract.py` 的三条，但去掉 trafilatura 依赖：
1. **看不见的字不算正文**（白字白底 / 0px / display:none 是经典的藏指令手法）；
2. 优先 `article` / `main`，去掉脚本、导航、页脚；
3. **数字不能丢**：主容器抽完若长数字串（价格/电话/时刻）丢超四成，退回去标签全文。
"""
from __future__ import annotations

import html as html_lib
import re

_LONG_NUM = re.compile(r"\d[\d\s\-()]{4,}\d")
_TAG_BLOCK = re.compile(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>")
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?![.\d])", re.I)
_HIDDEN_SIZE = re.compile(r"font-size\s*:\s*(?:0|1(?:\.\d+)?)\s*(?:px|pt)?\b", re.I)
_COLOR_PAIR = re.compile(
    r"(?:^|;)\s*(color|background(?:-color)?)\s*:\s*(#[0-9a-fA-F]{3,6})")
_BOILERPLATE = ("script", "style", "noscript", "svg", "nav", "footer",
                "aside", "form", "iframe")


def _hex6(value: str) -> str:
    text = value.lstrip("#").lower()
    return "".join(c * 2 for c in text) if len(text) == 3 else text


def _style_hidden(style: str) -> bool:
    if not style:
        return False
    if _HIDDEN_STYLE.search(style) or _HIDDEN_SIZE.search(style):
        return True
    got = {k.lower(): _hex6(v) for k, v in _COLOR_PAIR.findall(style)}
    fg = got.get("color")
    bg = got.get("background") or got.get("background-color")
    return bool(fg and bg and fg == bg)


def drop_hidden(raw: str) -> str:
    """删掉「看不见的节点」；lxml 不在 / 页面畸形时原样返回（降级，不抛）。"""
    if not raw:
        return raw or ""
    try:
        from lxml import html as lxml_html
        doc = lxml_html.fromstring(raw)
    except Exception:
        return raw
    if doc is None:
        return raw
    try:
        targets = [el for el in doc.xpath("//*[@style]")
                   if _style_hidden(el.get("style") or "")]
    except Exception:
        return raw
    if not targets:
        return raw
    for el in targets:
        try:
            el.drop_tree()
        except Exception:
            pass
    try:
        return lxml_html.tostring(doc, encoding="unicode")
    except Exception:
        return raw


def strip_tags(raw: str) -> str:
    """HTML → 纯文本（保留换行）。"""
    text = _TAG_BLOCK.sub(" ", raw or "")
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|table|section|article)>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def text_of(fragment: str) -> str:
    """一小段 HTML → 一行纯文本（搜索结果的标题/摘要用）。"""
    return re.sub(r"\s+", " ", html_lib.unescape(
        re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def title_of(raw: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw or "")
    return re.sub(r"\s+", " ", html_lib.unescape(match.group(1))).strip()[:200] if match else ""


def _digit_runs(text: str) -> set[str]:
    return {re.sub(r"\D", "", m) for m in _LONG_NUM.findall(text or "")} - {""}


def _main_container(raw: str) -> str:
    """优先 article / main；拿不到就交回整页。"""
    try:
        from lxml import html as lxml_html
        doc = lxml_html.fromstring(raw)
    except Exception:
        return ""
    if doc is None:
        return ""
    for xpath in ("//article", "//main", "//*[@role='main']"):
        try:
            nodes = doc.xpath(xpath)
        except Exception:
            nodes = []
        if not nodes:
            continue
        best = max(nodes, key=lambda el: len("".join(el.itertext())))
        for tag in _BOILERPLATE:
            for el in best.xpath(f".//{tag}"):
                try:
                    el.drop_tree()
                except Exception:
                    pass
        try:
            return lxml_html.tostring(best, encoding="unicode")
        except Exception:
            return ""
    return ""


def extract_text(raw: str) -> str:
    """整页 HTML → 正文纯文本。空输入返回空串。"""
    if not raw:
        return ""
    raw = drop_hidden(raw)
    full = strip_tags(raw)
    main_html = _main_container(raw)
    if not main_html:
        return full
    main = strip_tags(main_html)
    if len(main) < 800:
        return full                       # 主容器基本没抽出来 → 宁多别少
    want, got = _digit_runs(full), _digit_runs(main)
    if want and len(want - got) > 0.4 * len(want):
        return full                       # 数字丢太多（价格/电话在页脚或表格里）→ 回退全文
    return main


def clip_text(text: str, limit: int) -> str:
    """按上限裁剪，并告诉模型「原文还有多少字、可用 offset 继续读」。"""
    text = str(text or "")
    limit = max(200, int(limit or 8000))
    if len(text) <= limit:
        return text
    return (text[:limit]
            + f"\n\n（以上是前 {limit} 字；原文共 {len(text)} 字，"
              f"要更多请用 max_chars 调大重取或看更具体的网址。）")
