"""六级长句意群训练：整句听写，提交后按意群回放。

意群切分是确定性的（不调模型）：
- 标点（, ; : —）和从句/并列连词优先切；
- 过短的块合并，过长的块按真实停顿拆；
- 词级时间轴来自试卷 `transcript.json`，没有时间轴的试卷直接跳过。

卡片仍写 `wrong_items(source='cet6_chunk')`，复习仍走 `review_state`。
"""
from __future__ import annotations

import collections
import datetime as dt
import re

from learnsys import config, store
from learnsys.services.cet6 import drill as cet6_drill, paper as cet6_paper

_MIN_WORDS = 12
_MIN_CHUNK = 3
_MAX_CHUNK = 10
_MAX_CHUNKS = 5
_MAX_LIMIT = 8
_MAX_ANSWER = 4000

_PUNCT = (",", ";", ":", ".", "?", "!", "—", "–")
_CLAUSE = frozenset("""
when while because although though if unless since after before that which
who whom whose where whether as
""".split())
_COORD = frozenset("and but or so yet for".split())
_NORM_RE = re.compile(r"[^a-z0-9']+")


def normalize(token: str) -> str:
    return _NORM_RE.sub("", str(token or "").lower().replace("’", "'"))


def _align(text: str, words: list[tuple[float, float, str]]) -> tuple[list[str], list]:
    """把 data.js 的原文词对齐到 ASR 词级时间轴；对不上的按前后插值。"""
    tokens = str(text or "").split()
    if not tokens:
        return [], []
    times: list = [None] * len(tokens)
    cursor = 0
    for index, token in enumerate(tokens):
        key = normalize(token)
        if not key:
            continue
        for pos in range(cursor, min(len(words), cursor + 7)):
            if normalize(words[pos][2]) == key:
                times[index] = (words[pos][0], words[pos][1])
                cursor = pos + 1
                break
    known = [index for index, value in enumerate(times) if value]
    if len(known) < max(6, len(tokens) * 0.6):
        return tokens, []
    # 首尾和空洞都按相邻已知点插值；插值点只用于切块，不用于显示。
    for index in range(0, known[0]):
        times[index] = (times[known[0]][0], times[known[0]][0])
    for index in range(known[-1] + 1, len(times)):
        times[index] = (times[known[-1]][1], times[known[-1]][1])
    for left, right in zip(known, known[1:]):
        if right - left <= 1:
            continue
        start = times[left][1]
        stop = times[right][0]
        for index in range(left + 1, right):
            moment = start + (stop - start) * (index - left) / (right - left)
            times[index] = (moment, moment)
    return tokens, times


def align_tokens(text: str, words: list[tuple[float, float, str]]) -> tuple[list[str], list]:
    """把原文词对齐到词级时间轴；意群切分与纠音共用这一份。"""
    return _align(text, words)


def _split_long(chunks: list[list[int]], times: list) -> list[list[int]]:
    result: list[list[int]] = []
    for start, stop in chunks:
        stack = [(start, stop)]
        while stack:
            left, right = stack.pop()
            if right - left <= _MAX_CHUNK:
                result.append([left, right])
                continue
            best = None
            for cut in range(left + _MIN_CHUNK, right - _MIN_CHUNK + 1):
                if times[cut - 1] is None or times[cut] is None:
                    continue
                gap = times[cut][0] - times[cut - 1][1]
                if best is None or gap > best[0]:
                    best = (gap, cut)
            if best and best[0] >= 0.15:
                stack.append((best[1], right))
                stack.append((left, best[1]))
            else:
                result.append([left, right])
    return result


def build_chunks(text: str, words: list[tuple[float, float, str]],
                 clip_start: float, clip_end: float) -> list[dict]:
    """把一句切成语群；返回 `{text, start, end, words}`，时间相对句子音频。

    `clip_start` 是句子 mp3 的真实起点（句首 - 0.2 秒），不是 data.js 的句首；
    少了这 0.2 秒，回放会整体提前并吞掉上一块尾巴。
    """
    tokens, times = _align(text, words)
    if len(tokens) < _MIN_WORDS or not times:
        return []
    points = {0, len(tokens)}
    current = 0
    for index in range(1, len(tokens)):
        previous = tokens[index - 1].rstrip('"\')')
        key = normalize(tokens[index])
        length = index - current
        boundary = (
            (previous.endswith(_PUNCT) and length >= 2)
            or (key in _CLAUSE and length >= 3)
            or (key in _COORD and length >= 4)
        )
        if boundary:
            points.add(index)
            current = index
    ordered = sorted(points)
    chunks = [[ordered[k], ordered[k + 1]] for k in range(len(ordered) - 1)]

    # 过短的块并进相邻块
    changed = True
    while changed and len(chunks) > 1:
        changed = False
        for index, (start, stop) in enumerate(chunks):
            if stop - start >= _MIN_CHUNK:
                continue
            if index > 0:
                chunks[index - 1][1] = stop
                del chunks[index]
            else:
                chunks[index + 1][0] = start
                del chunks[index]
            changed = True
            break

    chunks = _split_long(chunks, times)

    # 一句话最多 5 个意群：合并最短的相邻两块
    while len(chunks) > _MAX_CHUNKS:
        index = min(range(len(chunks) - 1),
                    key=lambda k: (chunks[k][1] - chunks[k][0])
                    + (chunks[k + 1][1] - chunks[k + 1][0]))
        chunks[index][1] = chunks[index + 1][1]
        del chunks[index + 1]

    # 只剩一块时，按最大停顿再拆一次
    if len(chunks) == 1:
        start, stop = chunks[0]
        best = None
        for cut in range(start + 2, stop - 1):
            if times[cut - 1] is None or times[cut] is None:
                continue
            gap = times[cut][0] - times[cut - 1][1]
            if best is None or gap > best[0]:
                best = (gap, cut)
        if best and best[0] >= 0.12:
            chunks = [[start, best[1]], [best[1], stop]]
    if len(chunks) < 2:
        return []

    duration = max(0.0, float(clip_end) - float(clip_start))
    result: list[dict] = []
    for start, stop in chunks:
        first = times[start]
        last = times[stop - 1]
        if first is None or last is None:
            return []
        begin = max(0.0, float(first[0]) - float(clip_start) - 0.02)
        finish = min(duration, float(last[1]) - float(clip_start) + 0.02)
        if finish <= begin:
            return []
        result.append({
            "text": " ".join(tokens[start:stop]),
            "start": round(begin, 3),
            "end": round(finish, 3),
            "words": stop - start,
        })
    return result


def _since(days: int = 3) -> str:
    day = dt.date.today() - dt.timedelta(days=max(1, int(days or 3)))
    return f"{day.isoformat()} 00:00:00"


def _chunks_for_row(row: dict) -> list[dict]:
    data = cet6_paper.sentence_words(
        row["paper_title"], row["section"], row["item"], row["sentence"])
    if not data:
        return []
    return build_chunks(data["text"], data["words"],
                        data["clip_start"], data["end"])


def queue(conn, limit: int = 8) -> dict:
    """长句队列：A/B 段优先、有笔记的优先、练得少的先上。"""
    limit = max(1, min(int(limit or 8), _MAX_LIMIT))
    since = _since(3)
    has_library = (config.cet6_dir() / "试卷").is_dir()
    rows = store.chunk_candidates(conn, since=since, limit=max(limit * 10, 40))
    items: list[dict] = []
    for row in rows:
        if len(str(row.get("en") or "").split()) < _MIN_WORDS:
            continue
        chunks = _chunks_for_row(row)
        if len(chunks) < 2:
            continue
        audio = cet6_paper.audio_url(
            row["paper_title"], row["section"], row["item"],
            sentence=row["sentence"])
        if has_library and not audio:
            continue
        items.append({
            "paper_id": row["paper_id"],
            "paper_title": row["paper_title"],
            "section": row["section"],
            "section_letter": _section_letter(row["section"]),
            "item": row["item"],
            "sentence": row["sentence"],
            "word_count": len(str(row.get("en") or "").split()),
            "audio_url": audio,
            "source": "long",
        })
        if len(items) >= limit:
            break
    return {"items": items, "count": len(items)}


def _section_letter(section: str) -> str:
    match = re.search(r"Section\s+([A-C])", str(section or ""))
    return match.group(1) if match else "其他"


def attempt(conn, payload: dict) -> dict:
    paper_id = str(payload.get("paper_id") or "")
    section = str(payload.get("section") or "")
    item_name = str(payload.get("item") or "")
    try:
        sentence = int(payload.get("sentence") or 0)
    except (TypeError, ValueError):
        sentence = 0
    row = store.drill_sentence(
        conn, paper_id=paper_id, section=section, item=item_name,
        sentence=sentence)
    if row is None:
        raise LookupError("这句还没同步到后台，先回精听工作台打开一次")

    chunks = _chunks_for_row(row)
    if len(chunks) < 2:
        raise LookupError("这句拆不出意群，换一句或用逐句听写")

    answer = str(payload.get("answer") or "").strip()[:_MAX_ANSWER]
    diff = cet6_drill.diff_answer(row["en"], answer)
    cards = (cet6_drill._cards_for(conn, row, diff, answer,
                                   source="cet6_chunk") if answer else [])
    attempt_id = store.add_chunk_attempt(
        conn, paper_id=row["paper_id"], paper_title=row["paper_title"],
        section=row["section"], item=row["item"], sentence=row["sentence"],
        expected=row["en"], answer=answer, score=diff["score"],
        missed=diff["missed"], extra=diff["extra"],
        duration_s=int(payload.get("duration_s") or 0),
        cards_added=len(cards), chunk_count=len(chunks))
    return {
        "attempt_id": attempt_id,
        "expected": row["en"],
        "answer": answer,
        "score": diff["score"],
        "matched": diff["matched"],
        "total": diff["total"],
        "content_matched": diff["content_matched"],
        "content_total": diff["content_total"],
        "missed": diff["missed"],
        "extra": diff["extra"],
        "parts": diff["parts"],
        "chunks": chunks,
        "chunk_count": len(chunks),
        "audio_url": cet6_paper.audio_url(
            row["paper_title"], row["section"], row["item"],
            sentence=row["sentence"]),
        "cards": cards,
        "cards_created": len(cards),
    }


def _bucket() -> dict:
    return {"attempts": 0, "score": 0.0}


def _finish(bucket: dict) -> dict:
    count = bucket["attempts"]
    return {"attempts": count,
            "avg_score": round(bucket["score"] / count, 4) if count else 0.0}


def stats(conn, days: int = 30) -> dict:
    days = max(7, min(int(days or 30), 365))
    since = _since(days - 1)
    rows = store.chunk_attempts(conn, since=since)
    sections: dict[str, dict] = collections.defaultdict(_bucket)
    daily: dict[str, dict] = collections.defaultdict(_bucket)
    missed = collections.Counter()
    seen: set[tuple] = set()
    cards_added = 0
    score_total = 0.0
    for row in rows:
        score = float(row.get("score") or 0)
        score_total += score
        cards_added += int(row.get("cards_added") or 0)
        seen.add((row["paper_id"], row["section"], row["item"],
                  row["sentence"]))
        letter = _section_letter(row["section"])
        day = str(row.get("ts") or "")[:10]
        for bucket in (sections[letter], daily[day]):
            bucket["attempts"] += 1
            bucket["score"] += score
        for item in row.get("missed") or []:
            token = normalize(str(item.get("token") or ""))
            if token and len(token) > 1 and token not in cet6_drill._STOPWORDS:
                missed[token] += 1
    return {
        "range": {"days": days, "since": since[:10]},
        "total_attempts": len(rows),
        "sentences": len(seen),
        "avg_score": round(score_total / len(rows), 4) if rows else 0.0,
        "cards_added": cards_added,
        "by_section": {key: _finish(value)
                       for key, value in sorted(sections.items())},
        "daily": [{"date": day, **_finish(daily[day])}
                  for day in sorted(daily)][-14:],
        "top_missed": [{"token": token, "count": count}
                       for token, count in missed.most_common(20)],
    }
