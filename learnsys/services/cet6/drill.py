"""六级专项听写：队列、词级差异、自动建卡、统计。

口径：
- 队列优先取你在精听工作台记过笔记的句子，再补 A/B 段未练句；
- 提交后按“内容词”算分，漏听的内容词自动进 `wrong_items`；
- 卡片不另存一份，复习仍走 `review_state`，和写作/翻译共用一套 FSRS。
"""
from __future__ import annotations

import collections
import datetime as dt
import difflib
import re

from learnsys import config, store
from learnsys.services.cet6 import paper as cet6_paper

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")
_STOPWORDS = frozenset("""
a an the and or but nor so yet for of to in on at by with from as is are was were
be been being am do does did have has had will would can could may might must shall
should i you he she it we they me him her us them my your his its our their this that
these those there here not no if then than too very just also only about into over
under after before between during through while because although though when where
what which who whom whose how why all any both each few more most other some such own
same
""".split())
_MAX_CARDS = 6
_MAX_ANSWER = 4000


def tokenize(text: str) -> list[str]:
    return [match.group(0) for match in _WORD_RE.finditer(str(text or ""))]


def normalize(token: str) -> str:
    return str(token or "").lower().replace("’", "'")


def _annotate(text: str, missed: list[dict]) -> list[dict]:
    """把漏听词标出来，前端只负责渲染，不复制一套分词规则。"""
    missed_index = {int(item.get("index", -1)) for item in missed}
    parts: list[dict] = []
    last = 0
    for index, match in enumerate(_WORD_RE.finditer(text)):
        if index not in missed_index:
            continue
        if match.start() > last:
            parts.append({"text": text[last:match.start()], "miss": False})
        parts.append({"text": match.group(0), "miss": True})
        last = match.end()
    if last < len(text):
        parts.append({"text": text[last:], "miss": False})
    return parts


def diff_answer(expected: str, answer: str) -> dict:
    """词级差异；只按内容词算分，功能词漏掉不直接判低分。"""
    expected_tokens = tokenize(expected)
    answer_tokens = tokenize(answer)
    expected_norm = [normalize(token) for token in expected_tokens]
    answer_norm = [normalize(token) for token in answer_tokens]
    matcher = difflib.SequenceMatcher(
        None, expected_norm, answer_norm, autojunk=False)
    matched: set[int] = set()
    missed: list[dict] = []
    extra: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            matched.update(range(i1, i2))
        elif tag in ("replace", "delete"):
            for index in range(i1, i2):
                missed.append({"token": expected_tokens[index], "index": index})
            for index in range(j1, j2):
                extra.append(answer_tokens[index])
        elif tag == "insert":
            for index in range(j1, j2):
                extra.append(answer_tokens[index])
    content = [index for index, token in enumerate(expected_norm)
               if len(token) > 1 and token not in _STOPWORDS]
    if content:
        content_matched = sum(1 for index in content if index in matched)
        score = content_matched / len(content)
    elif expected_norm:
        content_matched = len(matched)
        score = len(matched) / len(expected_norm)
    else:
        content_matched = 0
        score = 0.0
    return {
        "score": round(score, 4),
        "matched": len(matched),
        "total": len(expected_norm),
        "content_matched": content_matched,
        "content_total": len(content),
        "missed": missed,
        "extra": extra,
        "parts": _annotate(str(expected or ""), missed),
    }


def _blank_question(sentence: str, token: str) -> str:
    pattern = re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])",
        re.IGNORECASE)
    if pattern.search(sentence):
        return pattern.sub("____", sentence, count=1)
    return f"听写：{sentence}"


def _cards_for(conn, row: dict, diff: dict, answer: str,
               source: str = "cet6_dictation") -> list[dict]:
    """漏听的内容词各建一张卡；同一句同一词只留一张。"""
    created: list[dict] = []
    seen: set[str] = set()
    for item in diff.get("missed") or []:
        token = str(item.get("token") or "")
        key = normalize(token)
        if len(token) < 2 or key in _STOPWORDS or key in seen:
            continue
        seen.add(key)
        question = _blank_question(row["en"], token)
        source_id = (f"{row['paper_title']}|{row['section']}|{row['item']}|"
                     f"{row['sentence']}|{key}")[:400]
        tags = "听辨、数字" if token.isdigit() else "听辨"
        _, is_new = store.add_wrong_item(
            conn, question=question, answer=token,
            my_answer=str(answer or "")[:500], tags=tags,
            note=f"原句：{row['en']}\n你的听写：{str(answer or '')[:500] or '（空）'}",
            source=source, source_id=source_id, auto=True)
        if is_new:
            created.append({"token": token, "question": question})
        if len(created) >= _MAX_CARDS:
            break
    if created:
        store.seed_review_states(conn)
    return created


def _audio_url(row: dict) -> str:
    """把进度行还原成 `/cet6/试卷/.../句子/NN.mp3`；路径规则统一在 `cet6_paper`。"""
    return cet6_paper.audio_url(
        row["paper_title"], row["section"], row["item"],
        sentence=int(row["sentence"]))


def audio_url_for_source(source_id: str) -> str:
    """从听辨卡的 source_id 还原原句音频；格式：卷名|段|题型|句号|目标词。"""
    parts = str(source_id or "").split("|")
    if len(parts) < 5:
        return ""
    try:
        sentence = int(parts[3])
    except (TypeError, ValueError):
        return ""
    return _audio_url({"paper_title": parts[0], "section": parts[1],
                       "item": parts[2], "sentence": sentence})


def _since(days: int = 3) -> str:
    day = dt.date.today() - dt.timedelta(days=max(1, int(days or 3)))
    return f"{day.isoformat()} 00:00:00"


def queue(conn, limit: int = 8) -> dict:
    """今日专项：约 3/4 来自笔记句，1/4 补 A/B 未练句。

    安装了六级音频目录时，跳过找不到 MP3 的句子；测试环境没有音频，
    就保留这些句子，接口仍可验证。
    """
    limit = max(1, min(int(limit or 8), 20))
    since = _since(3)
    has_library = (config.cet6_dir() / "试卷").is_dir()
    note_target = max(1, round(limit * 0.75))
    note_pool = store.drill_candidates(
        conn, since=since, limit=max(note_target * 6, 24))
    coverage_pool = store.drill_coverage_candidates(
        conn, since=since, limit=max((limit - note_target) * 6, 12))

    items: list[dict] = []
    used: set[tuple] = set()

    def pack(rows: list[dict], source: str, take: int) -> None:
        added = 0
        for row in rows:
            if added >= take:
                return
            key = (row["paper_id"], row["section"], row["item"], row["sentence"])
            if key in used:
                continue
            item = dict(row)
            item.pop("note", None)      # 笔记里可能写着答案，提交前不下发
            item["source"] = source
            item["audio_url"] = _audio_url(row)
            if has_library and not item["audio_url"]:
                continue
            used.add(key)
            items.append(item)
            added += 1

    pack(note_pool, "note", note_target)
    pack(coverage_pool, "coverage", limit - len(items))
    if len(items) < limit:
        pack(note_pool, "note", limit - len(items))
    return {"items": items, "count": len(items)}


def attempt(conn, payload: dict) -> dict:
    paper_id = str(payload.get("paper_id") or "")
    section = str(payload.get("section") or "")
    item = str(payload.get("item") or "")
    try:
        sentence = int(payload.get("sentence") or 0)
    except (TypeError, ValueError):
        sentence = 0
    row = store.drill_sentence(
        conn, paper_id=paper_id, section=section, item=item, sentence=sentence)
    if row is None:
        raise LookupError("这句还没同步到后台，先回精听工作台打开一次")

    answer = str(payload.get("answer") or "").strip()[:_MAX_ANSWER]
    diff = diff_answer(row["en"], answer)
    cards = _cards_for(conn, row, diff, answer) if answer else []
    attempt_id = store.add_drill_attempt(
        conn, paper_id=row["paper_id"], paper_title=row["paper_title"],
        section=row["section"], item=row["item"], sentence=row["sentence"],
        expected=row["en"], answer=answer, score=diff["score"],
        missed=diff["missed"], extra=diff["extra"],
        duration_s=int(payload.get("duration_s") or 0),
        cards_added=len(cards))
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
        "cards": cards,
        "cards_created": len(cards),
    }


def stats(conn, days: int = 30) -> dict:
    days = max(7, min(int(days or 30), 365))
    since = _since(days - 1)
    rows = store.drill_attempts(conn, since=since)
    section = collections.defaultdict(lambda: {"attempts": 0, "score": 0.0})
    daily = collections.defaultdict(lambda: {"attempts": 0, "score": 0.0})
    missed = collections.Counter()
    seen_sentences = set()
    cards_added = 0
    score_total = 0.0
    for row in rows:
        score = float(row.get("score") or 0)
        score_total += score
        cards_added += int(row.get("cards_added") or 0)
        seen_sentences.add((row["paper_id"], row["section"], row["item"],
                            row["sentence"]))
        slot = section[row["section"] or "未分段"]
        slot["attempts"] += 1
        slot["score"] += score
        day = str(row.get("ts") or "")[:10]
        bucket = daily[day]
        bucket["attempts"] += 1
        bucket["score"] += score
        for item in row.get("missed") or []:
            token = normalize(str(item.get("token") or ""))
            if token and token not in _STOPWORDS:
                missed[token] += 1

    def _finish(bucket: dict) -> dict:
        count = bucket["attempts"]
        return {"attempts": count,
                "avg_score": round(bucket["score"] / count, 4) if count else 0.0}

    return {
        "range": {"days": days, "since": since[:10]},
        "total_attempts": len(rows),
        "sentences": len(seen_sentences),
        "avg_score": round(score_total / len(rows), 4) if rows else 0.0,
        "cards_added": cards_added,
        "by_section": {key: _finish(value) for key, value in section.items()},
        "daily": [{"date": day, **_finish(daily[day])}
                  for day in sorted(daily)][-14:],
        "top_missed": [{"token": token, "count": count}
                       for token, count in missed.most_common(20)],
    }
