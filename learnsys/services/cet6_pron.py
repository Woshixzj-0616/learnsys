"""从精听笔记里提取「没听出 / 听成 / 不知道意思」的纠音点。

只做确定性解析，不调模型：
- 触发词：没听出、没听清、听不明白、没反应过来、不知道意思、听成、连读；
- 「听成 X」里的 X 记为你听到的；
- 目标词到原句里做模糊匹配，顺手修正笔记里的拼写偏差；
- 音频位置来自 `transcript.json` 的词级时间轴，只播目标词所在片段。
"""
from __future__ import annotations

import difflib
import re

from learnsys import store
from learnsys.services import cet6_chunk, cet6_paper

_TRIGGER_RE = re.compile(
    r"(没有听出来|没听出来|没有听出|没听出|没有听清|没听清|听不明白|没听懂|"
    r"没有反应过来|没反应过来|不知道意思|不懂意思|不理解|生词|听成|连读)")
_EN_RUN_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9'’&\-.]*(?:\s+[A-Za-z0-9][A-Za-z0-9'’&\-.]*)*")
_SENTENCE_SPLIT = re.compile(r"[。；;！!？?\n]+")
_KIND_ORDER = {"misheard": 0, "linking": 1, "vocab": 2, "reaction": 3,
               "unknown": 4}
_KIND_LABEL = {"misheard": "辨音", "linking": "连读", "vocab": "生词",
               "reaction": "反应", "unknown": "没听出"}


def _clean_run(raw: str) -> str:
    text = " ".join(str(raw or "").strip().split())
    text = text.strip(".,;:!?，。；：！？")
    if not text:
        return ""
    if len(text) < 2:
        return ""
    if len(text.split()) > 12:
        return ""
    return text


def _english_runs(text: str) -> list[tuple[int, int, str]]:
    runs: list[tuple[int, int, str]] = []
    for match in _EN_RUN_RE.finditer(str(text or "")):
        cleaned = _clean_run(match.group(0))
        if cleaned:
            runs.append((match.start(), match.end(), cleaned))
    return runs


def _classify(trigger: str, window: str) -> str:
    if trigger == "连读" or "连读" in window:
        return "linking"
    if trigger in ("不知道意思", "不懂意思") or "生词" in window:
        return "vocab"
    if "反应过来" in trigger:
        return "reaction"
    return "unknown"


def _merge(items: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for item in items:
        key = str(item["target"]).lower()
        if key not in merged:
            merged[key] = dict(item)
            order.append(key)
            continue
        current = merged[key]
        if item.get("heard_as") and not current.get("heard_as"):
            current["heard_as"] = item["heard_as"]
        if _KIND_ORDER.get(item.get("kind"), 9) < _KIND_ORDER.get(
                current.get("kind"), 9):
            current["kind"] = item.get("kind")
    return [merged[key] for key in order]


def extract_note(note: str) -> list[dict]:
    """把一条自由文本笔记拆成纠音条目；解析不出就返回空列表。"""
    items: list[dict] = []
    for segment in _SENTENCE_SPLIT.split(str(note or "")):
        segment = segment.strip()
        if not segment:
            continue
        matches = list(_TRIGGER_RE.finditer(segment))
        cursor = 0
        last_target = ""
        for index, match in enumerate(matches):
            trigger = match.group(1)
            window = segment[cursor:match.start()]
            before = _english_runs(window)
            next_start = (matches[index + 1].start()
                          if index + 1 < len(matches) else len(segment))
            after = _english_runs(segment[match.end():next_start])
            if trigger == "听成":
                target = before[-1][2] if before else last_target
                heard = after[0][2] if after else ""
                if target:
                    items.append({"target": target, "heard_as": heard,
                                  "kind": "misheard"})
                    last_target = target
                cursor = (match.end() + after[0][1]) if after else match.end()
                continue
            targets = [run[2] for run in before]
            if not targets and after:
                # 「没听出 effects」这种目标在触发词后面的写法
                targets = [after[0][2]]
            for target in targets:
                items.append({"target": target, "heard_as": "",
                              "kind": _classify(trigger, window)})
                last_target = target
            cursor = match.end()
    return _merge(items)


def _norm_word(word: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", str(word or "").lower())


def match_target(sentence: str, target: str):
    """在原文里找目标词/短语；返回 `(start, end, 修正后的原文)`。"""
    words = str(sentence or "").split()
    wanted = str(target or "").split()
    if not words or not wanted:
        return None
    norm_words = [_norm_word(word) for word in words]
    norm_wanted = [_norm_word(word) for word in wanted]
    if not any(norm_wanted):
        return None
    size = len(wanted)
    for start in range(0, len(words) - size + 1):
        if norm_words[start:start + size] == norm_wanted:
            return start, start + size, _clean_run(" ".join(words[start:start + size]))
    best = None
    for start in range(0, len(words) - size + 1):
        score = 0.0
        for left, right in zip(norm_words[start:start + size], norm_wanted):
            if left == right:
                score += 1.0
            elif left and right:
                ratio = difflib.SequenceMatcher(None, left, right).ratio()
                if ratio >= 0.8:
                    score += 0.85
        score /= size
        if best is None or score > best[0]:
            best = (score, start)
    if best and best[0] >= 0.6:
        start = best[1]
        return start, start + size, _clean_run(" ".join(words[start:start + size]))
    return None


def audio_segment(paper_title: str, section: str, item: str, sentence: int,
                  target: str) -> dict:
    """目标词在句子音频里的相对起止；找不到返回空字典。"""
    data = cet6_paper.sentence_words(paper_title, section, item, sentence)
    if not data:
        return {}
    tokens, times = cet6_chunk.align_tokens(data["text"], data["words"])
    if not times:
        return {}
    match = match_target(data["text"], target)
    if not match:
        return {}
    start_index, end_index, corrected = match
    first, last = times[start_index], times[end_index - 1]
    if not first or not last:
        return {}
    url = cet6_paper.audio_url(paper_title, section, item, sentence=sentence)
    if not url:
        return {}
    duration = max(0.0, float(data["end"]) - float(data["start"]))
    return {
        "url": url,
        "start": round(max(0.0, first[0] - data["start"] - 0.02), 3),
        "end": round(min(duration, last[1] - data["start"] + 0.02), 3),
        "corrected": corrected,
    }


def ensure_pool(conn) -> int:
    """把所有笔记重新过一遍；新词入库，旧词只刷新。返回新增条数。"""
    created = 0
    for row in store.note_rows(conn):
        for item in extract_note(row["note"]):
            target = item["target"]
            match = match_target(row["en"], target)
            if match:
                target = match[2]
            _, is_new = store.pron_upsert(
                conn, paper_id=row["paper_id"], paper_title=row["paper_title"],
                section=row["section"], item=row["item"],
                sentence=row["sentence"], target=target,
                heard_as=item["heard_as"], kind=item["kind"],
                note=row["note"], seen_at=row["updated_at"])
            created += 1 if is_new else 0
    return created


def kind_label(kind: str) -> str:
    return _KIND_LABEL.get(str(kind or ""), "没听出")


def payload(conn, item: dict) -> dict:
    """给每日页的展示包：原句、目标词音频、整句音频。"""
    sentence_row = store.drill_sentence(
        conn, paper_id=item["paper_id"], section=item["section"],
        item=item["item"], sentence=item["sentence"])
    sentence_text = sentence_row["en"] if sentence_row else ""
    segment = audio_segment(item["paper_title"], item["section"], item["item"],
                            item["sentence"], item["target"])
    sentence_audio = cet6_paper.audio_url(
        item["paper_title"], item["section"], item["item"],
        sentence=item["sentence"])
    return {
        "pron_id": item["id"],
        "target": item["target"],
        "heard_as": item["heard_as"],
        "kind": item["kind"],
        "kind_label": kind_label(item["kind"]),
        "note": item["note"],
        "sentence": sentence_text,
        "paper_title": item["paper_title"],
        "section": item["section"],
        "item": item["item"],
        "sentence_no": item["sentence"],
        "audio": segment,
        "sentence_audio": sentence_audio,
        "status": item["status"],
        "attempts": item["attempts"],
    }
