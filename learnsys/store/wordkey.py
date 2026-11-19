"""生词词形归一：只识别高置信变体，不做同义词推断。

生词本里同一个词可能以不同写法出现：

- 大小写 / 标点 / 撇号：`New Year's Eve` / `New Years Eve`
- 冠词：`the Silk Road` / `Silk Road`
- 单复数：`Caravans` / `caravan`
- 斜杠同义项：`remote medicine / telemedicine` / `remote medicine`
- 括号缩写：`digital RMB (e-CNY)` / `digital RMB`

这里只把这些「明显是同一个词」的写法归一成 alias 集合；
`high-speed rail` / `high-speed railway` 这类同义但拼写不同的，不自动合并，
由迁移工具单独列出来给人确认。

规则只写这一份：`store/vocab.py`、`store/review.py`、每日积累和迁移工具都调用它。
"""
from __future__ import annotations

import re
import unicodedata

_PARENS = re.compile(r"\([^)]*\)")
_SLASH = re.compile(r"\s*[/／]\s*")
_NON_WORD = re.compile(r"[^0-9a-z一-鿿\s]+")
_THE = re.compile(r"^the\s+")
_APOSTROPHE = re.compile(r"['’`]")


def _singular(token: str) -> str:
    """保守单数化：只处理明确的复数后缀，短词和 ss/us/is 结尾不动。"""
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and re.search(r"(s|x|z|ch|sh)es$", token):
        return token[:-2]
    if token.endswith("s") and not re.search(r"(ss|us|is)$", token):
        return token[:-1]
    return token


def _singular_phrase(phrase: str) -> str:
    words = phrase.split()
    if not words:
        return phrase
    words[-1] = _singular(words[-1])
    return " ".join(words)


def word_aliases(word: str) -> set[str]:
    """返回一个词的所有高置信写法（小写、去标点、去 the、拆斜杠、单数化）。"""
    text = unicodedata.normalize("NFKD", str(word or "")).lower()
    text = _APOSTROPHE.sub("", text)
    # 括号里的缩写也算一种写法：digital RMB (e-CNY) 应能匹配 e-CNY。
    parens = [value for value in _PARENS.findall(text)]
    text = _PARENS.sub(" ", text)
    parts = _SLASH.split(text) + parens
    aliases: set[str] = set()
    # 先按斜杠拆，再清标点；否则 `/` 会先被清掉，同义项就分不开了。
    for part in parts:
        part = _NON_WORD.sub(" ", part)
        part = " ".join(part.split())
        part = _THE.sub("", part).strip()
        if not part:
            continue
        aliases.add(part)
        singular = _singular_phrase(part)
        if singular:
            aliases.add(singular)
    return aliases


def aliases_match(left: str, right: str) -> bool:
    """两个词是否有至少一个相同的 alias。"""
    return bool(word_aliases(left) & word_aliases(right))


def meanings_compatible(left: str, right: str) -> bool:
    """两条释义有中文交集才算同一个词；glass / glasses 这种要分开。"""
    left_units = {ch for ch in str(left or "") if 0x4E00 <= ord(ch) <= 0x9FFF}
    right_units = {ch for ch in str(right or "") if 0x4E00 <= ord(ch) <= 0x9FFF}
    if not left_units or not right_units:
        return True
    return bool(left_units & right_units)


def variant_groups(items: list[dict]) -> list[list[dict]]:
    """按 alias 连通分量分组；只返回至少两条的组。纯函数，不碰数据库。"""
    rows = list(items or [])
    if len(rows) < 2:
        return []
    parent = list(range(len(rows)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_alias: dict[str, list[int]] = {}
    for index, item in enumerate(rows):
        for alias in word_aliases(item.get("word")):
            by_alias.setdefault(alias, []).append(index)
    for indexes in by_alias.values():
        for other in indexes[1:]:
            union(indexes[0], other)

    grouped: dict[int, list[dict]] = {}
    for index, item in enumerate(rows):
        grouped.setdefault(root(index), []).append(item)
    return [group for group in grouped.values() if len(group) > 1]


def is_plural_phrase(word: str) -> bool:
    """只看最后一个词是否被单数化过；给迁移工具挑更清楚的显示词形用。"""
    text = unicodedata.normalize("NFKD", str(word or "")).lower()
    text = _PARENS.sub(" ", text)
    text = _APOSTROPHE.sub("", text)
    words = _NON_WORD.sub(" ", text).split()
    if not words:
        return False
    return _singular(words[-1]) != words[-1]
