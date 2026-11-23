"""每日积累的翻译选词：按「最久没推过」轮换，近 30 天不重复。

旧做法按 `日期 × 每天条数` 在词库里平移下标，词库轮完一圈后必然重复；
生词本又会吃掉一部分词，实际可用池比库大小更小。现在改成按历史排序：

1. 从没推过的词优先（按库内顺序）；
2. 其次 30 天前推过的（按上次推送日期从早到晚）；
3. 最近 30 天推过的排最后，只有前两档凑不满时才用，并标 `repeat`。

高频短语每天 4 条；主题词每天 4 条且来自不同篇目，避免一天只考一个主题。
某一类凑不满时由另一类补足，但仍然宁缺毋滥，不硬凑重复词。
"""
from __future__ import annotations

import datetime as dt

from learnsys import store
from learnsys.train import content as train_content

RECENT_DAYS = 30
DAILY_TOTAL = 8
PHRASE_PER_DAY = 4


def _history_last_seen(conn) -> dict[str, str]:
    """alias -> 最近一次被每日积累推送的日期（ISO 字符串）。"""
    seen: dict[str, str] = {}
    for item in store.accum_payloads(conn, kind="translation"):
        day = str(item.get("day") or "")[:10]
        for alias in store.word_aliases(str(item["payload"].get("en") or "")):
            if day > seen.get(alias, ""):
                seen[alias] = day
    return seen


def _last_seen_of(last_seen: dict[str, str], en: str) -> str:
    return max((last_seen.get(alias, "") for alias in store.word_aliases(en)),
               default="")


def _rank_key(last_seen: dict[str, str], cutoff: str, en: str,
              group_index: int, item_index: int) -> tuple:
    seen = _last_seen_of(last_seen, en)
    if not seen:
        tier = 0
    elif seen < cutoff:
        tier = 1
    else:
        tier = 2
    return (tier, seen, group_index, item_index)


class _Picker:
    """一次选词过程的状态：已选中文/英文 alias、结果列表、生词本排除集合。"""

    def __init__(self, vocab_aliases: set[str], last_seen: dict[str, str],
                 cutoff: str) -> None:
        self.vocab_aliases = vocab_aliases
        self.last_seen = last_seen
        self.cutoff = cutoff
        self.chosen_zh: set[str] = set()
        self.chosen_en: set[str] = set()
        self.rows: list[dict] = []

    def usable(self, zh: str, en: str) -> bool:
        if not zh or not en:
            return False
        aliases = store.word_aliases(en)
        if not aliases or aliases & self.vocab_aliases:
            return False
        if zh in self.chosen_zh or aliases & self.chosen_en:
            return False
        return True

    def take(self, row: dict, zh: str, en: str) -> None:
        self.chosen_zh.add(zh)
        self.chosen_en.update(store.word_aliases(en))
        repeat = _last_seen_of(self.last_seen, en) >= self.cutoff
        payload = dict(row["payload"])
        if repeat:
            payload["repeat"] = True
        self.rows.append({"ref_key": row["ref_key"], "payload": payload})

    def key(self, en: str, group_index: int, item_index: int) -> tuple:
        return _rank_key(self.last_seen, self.cutoff, en,
                         group_index, item_index)


def _phrase_rows() -> list[dict]:
    rows = train_content.translation_phrases()
    return [row for row in rows
            if isinstance(row, dict) and str(row.get("zh") or "").strip()
            and str(row.get("en") or "").strip()]


def _theme_groups() -> list[tuple[dict, list[dict]]]:
    """按篇目分组；同一中文只归第一个篇目，避免两个篇目抢同一个词。"""
    groups: list[tuple[dict, list[dict]]] = []
    seen: set[str] = set()
    for item in train_content.library()["translation"]:
        terms = []
        for term in item.get("terms") or []:
            if not isinstance(term, dict):
                continue
            zh = str(term.get("zh") or "").strip()
            en = str(term.get("en") or "").strip()
            if not zh or not en or zh in seen:
                continue
            seen.add(zh)
            terms.append(term)
        if terms:
            groups.append((item, terms))
    return groups


def _phrase_row(phrase: dict) -> dict:
    return {
        "ref_key": f"phrase:{phrase.get('id')}",
        "payload": {
            "zh": str(phrase.get("zh") or "").strip(),
            "en": str(phrase.get("en") or "").strip(),
            "note": str(phrase.get("note") or "").strip(),
            "theme": str(phrase.get("theme") or "").strip(),
            "tag": "高频短语",
            "source_id": str(phrase.get("id") or ""),
        },
    }


def _term_row(item: dict, term: dict) -> dict:
    zh = str(term.get("zh") or "").strip()
    return {
        "ref_key": f"term:{item.get('id')}:{zh}",
        "payload": {
            "zh": zh,
            "en": str(term.get("en") or "").strip(),
            "note": str(term.get("note") or "").strip(),
            "theme": str(item.get("theme") or "").strip(),
            "tag": "主题词",
            "source_id": f"{item.get('id')}:{zh}",
        },
    }


def pick_translation(conn, day: str) -> list[dict]:
    """给某一天挑翻译词；只读，不写库。"""
    day = str(day or "")[:10]
    cutoff = (dt.date.fromisoformat(day)
              - dt.timedelta(days=RECENT_DAYS)).isoformat()
    picker = _Picker(store.active_vocab_aliases(conn),
                     _history_last_seen(conn), cutoff)

    # 1) 高频短语：固定 4 条，从没推过的排最前。
    # 排序前先去掉生词本里的词：否则排序靠前的词被 usable 跳过，
    # 实际取到的是排序靠后的「最近刚推过」的词。
    phrases = [row for row in _phrase_rows()
               if not (store.word_aliases(str(row["en"])) & picker.vocab_aliases)]
    ranked_phrases = sorted(
        ((row, index) for index, row in enumerate(phrases)),
        key=lambda pair: picker.key(str(pair[0]["en"]), 0, pair[1]))
    picked_phrases = 0
    for phrase, index in ranked_phrases:
        if picked_phrases >= PHRASE_PER_DAY:
            break
        zh = str(phrase.get("zh") or "").strip()
        en = str(phrase.get("en") or "").strip()
        if not picker.usable(zh, en):
            continue
        picker.take(_phrase_row(phrase), zh, en)
        picked_phrases += 1

    # 2) 主题词：先取来自不同篇目的 4 条。
    ranked_groups = []
    for group_index, (item, terms) in enumerate(_theme_groups()):
        # 同短语：先排除生词本，再按「最久未推」排序；
        # 整组都被生词本吃掉时，这组当天不参与。
        available = [term for term in terms
                     if not (store.word_aliases(str(term.get("en") or ""))
                             & picker.vocab_aliases)]
        ranked_terms = sorted(
            ((term, index) for index, term in enumerate(available)),
            key=lambda pair: picker.key(str(pair[0].get("en") or ""),
                                        group_index, pair[1]))
        if ranked_terms:
            ranked_groups.append((item, ranked_terms, group_index))
    ranked_groups.sort(key=lambda group: picker.key(
        str(group[1][0][0].get("en") or ""), group[2], group[1][0][1]))

    used_groups: set[str] = set()
    picked_terms = 0
    target_terms = min(DAILY_TOTAL - len(picker.rows),
                       DAILY_TOTAL - PHRASE_PER_DAY)
    for item, ranked_terms, _group_index in ranked_groups:
        if picked_terms >= target_terms:
            break
        group_id = str(item.get("id") or "")
        if group_id in used_groups:
            continue
        for term, _index in ranked_terms:
            zh = str(term.get("zh") or "").strip()
            en = str(term.get("en") or "").strip()
            if not picker.usable(zh, en):
                continue
            picker.take(_term_row(item, term), zh, en)
            used_groups.add(group_id)
            picked_terms += 1
            break

    # 3) 不足 8 条时用另一类补：先主题词剩余，再短语剩余。
    if len(picker.rows) < DAILY_TOTAL:
        for item, ranked_terms, _group_index in ranked_groups:
            if len(picker.rows) >= DAILY_TOTAL:
                break
            for term, _index in ranked_terms:
                zh = str(term.get("zh") or "").strip()
                en = str(term.get("en") or "").strip()
                if not picker.usable(zh, en):
                    continue
                picker.take(_term_row(item, term), zh, en)
                if len(picker.rows) >= DAILY_TOTAL:
                    break
    if len(picker.rows) < DAILY_TOTAL:
        for phrase, _index in ranked_phrases:
            if len(picker.rows) >= DAILY_TOTAL:
                break
            zh = str(phrase.get("zh") or "").strip()
            en = str(phrase.get("en") or "").strip()
            if not picker.usable(zh, en):
                continue
            picker.take(_phrase_row(phrase), zh, en)
    return picker.rows
