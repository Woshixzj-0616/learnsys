# -*- coding: utf-8 -*-
"""通用英语听力分割器 v1。

把一个完整的英语听力音频按题型拆分：
  Section A/B/C -> Conversation / Passage / Recording -> 正文 / 题目 -> 逐句

用法：
  python split_listening.py 音频.mp3
  python split_listening.py 音频.mp3 --out 输出目录
  python split_listening.py 音频.mp3 --transcript 已有转写.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# PyAV 19 与 faster-whisper 1.2.1 的兼容 shim
import av
_original_av_open = av.open


def _compat_av_open(*args, **kwargs):
    kwargs.pop("metadata_errors", None)
    return _original_av_open(*args, **kwargs)


av.open = _compat_av_open

from faster_whisper import WhisperModel  # noqa: E402
import imageio_ffmpeg  # noqa: E402

from transcript_fixes import apply_to_paper as apply_transcript_fixes  # noqa: E402
from audio_snap import detect_silences, snap_ends  # noqa: E402

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = TOOL_DIR / "models" / "base.en"
TEMPLATE = TOOL_DIR / "workbench_template.html"

NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}
ITEM_KIND_WORDS = {"conversation", "passage", "recording", "lecture", "talk"}
KIND_TITLE = {
    "conversation": "Conversation",
    "passage": "Passage",
    "recording": "Recording",
    "news report": "News Report",
    "lecture": "Lecture",
    "talk": "Talk",
    "": "Item",
}

QBLOCK_RE = re.compile(
    r"\bquestions?\s+(\d+)(?:\s+to\s+(\d+))?\s+(?:are|is)\s+based\s+on\s+the\s+"
    r"(conversation|passage|recording|news report|lecture|talk)\b"
)


# ---------------------------------------------------------------- 数据结构
@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Event:
    kind: str
    time: float
    cue_end: float
    section: str = ""
    item_kind: str = ""
    number: int = 0
    q_start: int = 0
    q_end: int = 0
    question_end: float = 0.0
    end_time: float = 0.0
    text: str = ""


# ---------------------------------------------------------------- 基础工具
def fmt_time(sec: float) -> str:
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:02d}:{s:05.2f}"


def fmt_short(sec: float) -> str:
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m}:{s:02d}"


def norm_word(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"(\d+)\s*[-–—]\s*(\d+)", r"\1 to \2", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return NUM_WORDS.get(text, text)


def token_pairs(seg: Segment) -> list[tuple[str, Word]]:
    out = []
    for w in seg.words:
        t = norm_word(w.text)
        if t:
            out.append((t, w))
    return out


def join_words(words: list[Word]) -> str:
    text = " ".join(w.text.strip() for w in words)
    text = re.sub(r"\s+([,.;:!?%])", r"\1", text)
    text = re.sub(r"\s+'", "'", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def words_between(flat: list[Word], start: float, end: float) -> list[Word]:
    return [w for w in flat if w.start >= start - 0.05 and w.start < end]


def text_between(flat: list[Word], start: float, end: float) -> str:
    return join_words(words_between(flat, start, end))


def dedup_events(events: list[Event], key, tol: float = 1.5) -> list[Event]:
    events = sorted(events, key=lambda e: e.time)
    out = []
    for e in events:
        if out and abs(e.time - out[-1].time) < tol and key(e) == key(out[-1]):
            continue
        out.append(e)
    return out


# ---------------------------------------------------------------- 线索识别
SECTION_RE = re.compile(r"\bsection\s+([abc])\b")
ITEM_RE = re.compile(r"\b(conversation|passage|recording|lecture|talk)\s+(\d+)\b")
NEWS_RE = re.compile(r"\bnews\s+report\s+(\d+)\b")
_QSEP = r"(?:\s*(?:to|through|and|-|–)?\s*(\d+))?"
QBLOCK_RE = re.compile(
    r"\bquestions?\s+(\d+)" + _QSEP + r"\s+(?:are|is)\s+based\s+on\s+the\s+"
    r"(conversation|passage|recording|news report|lecture|talk)\b"
)
# ASR 有时漏掉 "Questions"，只剩 "1 to 4 are based on the conversation"
QBLOCK_BARE_RE = re.compile(
    r"\b(\d+)" + _QSEP + r"\s+(?:are|is)\s+based\s+on\s+the\s+"
    r"(conversation|passage|recording|news report|lecture|talk)\b"
)
QUESTION_RE = re.compile(r"\bquestion\s+(\d+)\b")
END_RE = re.compile(r"\bend\s+of\s+listening\b")
DIREND_RES = [
    re.compile(r"\bwith\s+a\s+single\s+line\s+through\s+the\s+center\b"),
    re.compile(r"\banswer\s+sheet\b"),
]


def norm_char(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9\-]+", " ", text).strip()
    if text in NUM_WORDS:
        return NUM_WORDS[text]
    return text


def build_global_text(flat: list[Word]) -> tuple[str, list[int]]:
    """把全部词拼成一个字符串，并记录每个字符对应的词下标。"""
    parts: list[str] = []
    cmap: list[int] = []
    for wi, w in enumerate(flat):
        t = norm_char(w.text)
        if not t:
            continue
        if parts:
            parts.append(" ")
            cmap.append(wi)
        for ch in t:
            parts.append(ch)
            cmap.append(wi)
    return "".join(parts), cmap


def regex_events(text: str, cmap: list[int], flat: list[Word],
                 regex: re.Pattern, kind: str, apply) -> list[Event]:
    out = []
    for m in regex.finditer(text):
        s, e = m.start(), m.end() - 1
        while s < len(text) and text[s].isspace():
            s += 1
        while e >= 0 and text[e].isspace():
            e -= 1
        if s >= len(cmap) or e < 0 or e >= len(cmap):
            continue
        ev = Event(kind, flat[cmap[s]].start, flat[cmap[e]].end, text=m.group(0))
        apply(ev, m)
        out.append(ev)
    return out


def extract_events(flat: list[Word]):
    text, cmap = build_global_text(flat)

    def apply_section(ev, m):
        ev.section = m.group(1).upper()

    def apply_item(ev, m):
        ev.item_kind = m.group(1)
        ev.number = int(m.group(2))

    def apply_news(ev, m):
        ev.item_kind = "news report"
        ev.number = int(m.group(1))

    def apply_qblock(ev, m):
        ev.q_start = int(m.group(1))
        ev.q_end = int(m.group(2) or m.group(1))
        ev.item_kind = m.group(3)

    def apply_question(ev, m):
        ev.number = int(m.group(1))

    sections = regex_events(text, cmap, flat, SECTION_RE, "section", apply_section)
    items = regex_events(text, cmap, flat, ITEM_RE, "item", apply_item)
    items += regex_events(text, cmap, flat, NEWS_RE, "item", apply_news)
    qblocks = regex_events(text, cmap, flat, QBLOCK_RE, "qblock", apply_qblock)
    qblocks += regex_events(text, cmap, flat, QBLOCK_BARE_RE, "qblock", apply_qblock)
    questions = regex_events(text, cmap, flat, QUESTION_RE, "question", apply_question)
    ends = regex_events(text, cmap, flat, END_RE, "end", lambda ev, m: None)
    dirends = []
    for rx in DIREND_RES:
        dirends += regex_events(text, cmap, flat, rx, "dirend", lambda ev, m: None)

    # 题目块里的“Question 16-18”是题目范围，不是单独一道题
    questions = [
        q for q in questions
        if not any(qb.time - 1.0 <= q.time <= qb.cue_end + 1.0 for qb in qblocks)
    ]
    return sections, items, qblocks, questions, ends, dirends


# ---------------------------------------------------------------- 结构组装
def letter_for_question(n: int) -> str:
    """CET-6 听力固定题号区间：1-8 A，9-15 B，16-25 C。"""
    if 1 <= n <= 8:
        return "A"
    if 9 <= n <= 15:
        return "B"
    if 16 <= n <= 25:
        return "C"
    return ""


def canonical_sections(sections: list[Event], qblocks: list[Event],
                       warnings: list[str]) -> list[Event]:
    """用题号区间校正 Section 归属。

    音频开头常把 "section A/B/C" 当说明词重复念，或漏念某个 Section 标题，
    会让后续题型挂到错误的 Section 下。题号区间是硬约定，优先级高于标题词。
    只在题号能覆盖 A/B/C 三段时启用，其余情况保持原样。
    """
    letters = {letter_for_question(q.q_start) for q in qblocks}
    if letters != {"A", "B", "C"}:
        return sections
    out: list[Event] = []
    for letter in ("A", "B", "C"):
        qs = [q for q in qblocks if letter_for_question(q.q_start) == letter]
        if not qs:
            return sections
        first = min(q.time for q in qs)
        cands = [s for s in sections if s.section == letter and s.time <= first]
        if cands:
            out.append(max(cands, key=lambda s: s.time))
        else:
            at = max(0.0, first - 300.0)
            out.append(Event("section", at, at, section=letter))
            warnings.append(f"未识别到 Section {letter} 标题，按题号区间补建。")
    # 保持 A→B→C 的题号顺序：section_for 按列表顺序判定，不能按音频时间重排
    return out


def section_for(t: float, sections: list[Event]) -> Event:
    current = sections[0]
    for sec in sections:
        if sec.time <= t:
            current = sec
    return current


def directions_end_for(sec: Event, segs: list[Segment],
                       dirends: list[Event], first_q: float) -> float:
    candidates = [d for d in dirends if sec.time <= d.time < first_q]
    if candidates:
        return max(d.cue_end for d in candidates) + 0.1
    # 没有口令终止句时，用第一个超过 1 秒的停顿兜底
    prev_end = sec.time
    for seg in segs:
        if seg.start < sec.time:
            continue
        if seg.start >= first_q:
            break
        if seg.start - prev_end > 1.0 and seg.start > sec.time + 1.0:
            return prev_end + 0.1
        prev_end = max(prev_end, seg.end)
    return sec.time + 2.0


def split_sentences(words: list[Word], max_gap: float = 0.75,
                    max_len: float = 18.0) -> list[list[Word]]:
    if not words:
        return []
    sentences: list[list[Word]] = []
    cur: list[Word] = []
    for i, w in enumerate(words):
        cur.append(w)
        text = w.text.strip()
        end_punct = text.endswith((".", "?", "!", "。", "？", "！"))
        gap_next = (words[i + 1].start - w.end) if i + 1 < len(words) else 99.0
        duration = cur[-1].end - cur[0].start
        if len(cur) >= 3 and end_punct:
            sentences.append(cur)
            cur = []
        elif len(cur) >= 4 and gap_next > max_gap:
            sentences.append(cur)
            cur = []
        elif len(cur) >= 25 and duration > max_len and gap_next > 0.3:
            sentences.append(cur)
            cur = []
    if cur:
        if sentences and (len(cur) < 3 or cur[-1].end - cur[0].start < 1.0):
            sentences[-1].extend(cur)
        else:
            sentences.append(cur)

    merged: list[list[Word]] = []
    for s in sentences:
        if merged and (len(s) < 3 or s[-1].end - s[0].start < 1.2):
            merged[-1].extend(s)
        else:
            merged.append(s)
    return merged


def build_structure(segs: list[Segment], duration: float, warnings: list[str]):
    flat = [w for seg in segs for w in seg.words]
    flat.sort(key=lambda w: w.start)
    sections, items, qblocks, questions, ends, dirends = extract_events(flat)

    sections = dedup_events(sections, lambda e: e.section, 2.0)
    items = dedup_events(items, lambda e: (e.item_kind, e.number), 2.0)
    qblocks = dedup_events(qblocks, lambda e: (e.q_start, e.q_end), 1.5)
    questions = dedup_events(questions, lambda e: e.number, 1.0)

    end_time = ends[0].time if ends else (segs[-1].end if segs else duration)
    if not sections:
        first = segs[0].start if segs else 0.0
        sections = [Event("section", first, first, section="未分类")]
        warnings.append("未识别到 Section 提示，按未分类处理。")

    for i, sec in enumerate(sections):
        sec.end_time = sections[i + 1].time if i + 1 < len(sections) else end_time

    sections = canonical_sections(sections, qblocks, warnings)
    for i, sec in enumerate(sections):
        sec.end_time = sections[i + 1].time if i + 1 < len(sections) else end_time

    by_letter = {sec.section: sec for sec in sections}

    def section_of_q(q: Event) -> Event:
        return by_letter.get(letter_for_question(q.q_start)) or section_for(q.time, sections)

    def section_of_item(it: Event) -> Event:
        letter = {"conversation": "A", "passage": "B", "recording": "C",
                  "lecture": "C", "talk": "C"}.get(it.item_kind)
        return by_letter.get(letter) or section_for(it.time, sections)

    for q in qblocks:
        q.section = section_of_q(q).section

    section_items: dict[int, list[dict]] = {id(sec): [] for sec in sections}
    used_cues: set[int] = set()

    for qi, q in enumerate(qblocks):
        sec = section_of_q(q)
        prev_q = qblocks[qi - 1] if qi > 0 else None
        lower = max(sec.time, prev_q.time if prev_q else sec.time)
        cues = [
            it for it in items
            if lower < it.time < q.time and section_of_item(it) is sec
        ]
        cue = cues[-1] if cues else None

        if cue:
            content_start = cue.cue_end + 0.05
            kind = cue.item_kind or q.item_kind
            number = cue.number
            used_cues.add(id(cue))
        else:
            if prev_q and prev_q.section == sec.section:
                content_start = prev_q.question_end + 0.3
            else:
                qs_in_sec = [x for x in qblocks if x.section == sec.section]
                content_start = directions_end_for(
                    sec, segs, dirends, qs_in_sec[0].time if qs_in_sec else sec.end_time
                )
            kind = q.item_kind
            number = 0
            warnings.append(
                f"{sec.section} 段第 {q.q_start} 题前未识别到题型标题，"
                "已用题目块/停顿兜底。"
            )

        content_end = q.time - 0.2
        # 标题线索离题目块太近（<30 秒），多半是误识别词（如 "lecture 15"），
        # 改用上一块题目结束后的位置作为正文起点。
        if cue and content_end - content_start < 30.0:
            if prev_q and prev_q.section == sec.section:
                content_start = prev_q.question_end + 0.3
            else:
                qs_in_sec = [x for x in qblocks if x.section == sec.section]
                content_start = directions_end_for(
                    sec, segs, dirends, qs_in_sec[0].time if qs_in_sec else sec.end_time
                )
            kind = q.item_kind
            number = 0
        next_cue = next(
            (it for it in items
             if it.time > q.time and section_of_item(it) is sec),
            None,
        )
        next_sec = next((s for s in sections if s.time > q.time), None)
        next_q = qblocks[qi + 1] if qi + 1 < len(qblocks) else None

        # 题目音频的结束点优先用「本块最后一道题的朗读结束 + 答题停顿」，
        # 否则会一路延伸到下一个 Section，把下一段正文挤成负区间。
        q_events = [
            x for x in questions
            if q.time <= x.time < (next_q.time if next_q else end_time)
        ]
        if q_events:
            last_q_end = max(x.cue_end for x in q_events)
            prev_end = last_q_end
            for seg in segs:
                if seg.end <= last_q_end:
                    continue
                if seg.start - prev_end > 2.0:
                    break
                prev_end = max(prev_end, seg.end)
                if prev_end - last_q_end >= 40.0:
                    break
            q.question_end = min(
                prev_end + 0.3,
                next_q.time if next_q else end_time,
            )
        else:
            q_candidates = [
                x for x in [
                    next_cue.time if next_cue else None,
                    next_q.time if next_q else None,
                    next_sec.time if next_sec else None,
                    end_time,
                ] if x is not None
            ]
            q.question_end = min(q_candidates)

        if content_end <= content_start + 0.5:
            warnings.append(
                f"{sec.section} 段第 {q.q_start} 题正文区间过短，已跳过。"
            )
            continue

        section_items[id(sec)].append({
            "kind": kind,
            "number": number,
            "content_start": content_start,
            "content_end": content_end,
            "questions_start": q.time,
            "questions_end": q.question_end,
        })

    # 有标题、但没有对应题目块的段落（例如单篇讲座）
    for it in items:
        if id(it) in used_cues:
            continue
        sec = section_of_item(it)
        # 同题型同号已经存在（例如题目块已经吃掉了这个标题），才视为重复
        if any(x["kind"] == it.item_kind and x["number"] == it.number
               for x in section_items[id(sec)]):
            continue
        next_cue = next(
            (x for x in items
             if x.time > it.time and section_of_item(x) is sec),
            None,
        )
        next_sec = next((s for s in sections if s.time > it.time), None)
        candidates = [
            x for x in [
                next_cue.time if next_cue else None,
                next_sec.time if next_sec else None,
                end_time,
            ] if x is not None
        ]
        content_start = it.cue_end + 0.05
        content_end = min(candidates) - 0.2
        if content_end <= content_start + 0.5:
            continue
        if content_end - content_start < 60.0:
            # 没有题目块、又不足 1 分钟的段落，多半是 Section 指令里的播放提示词
            continue
        section_items[id(sec)].append({
            "kind": it.item_kind,
            "number": it.number,
            "content_start": content_start,
            "content_end": content_end,
            "questions_start": 0.0,
            "questions_end": 0.0,
        })

    # 完全没有结构线索：按单篇处理
    if not any(section_items.values()):
        first = segs[0].start if segs else 0.0
        section_items[id(sections[0])].append({
            "kind": "",
            "number": 1,
            "content_start": first,
            "content_end": end_time,
            "questions_start": 0.0,
            "questions_end": 0.0,
        })
        warnings.append("未识别到题型结构，按单篇音频处理。")

    return sections, section_items, qblocks, questions, end_time, dirends


# ---------------------------------------------------------------- 输出
def cut_audio(ffmpeg: str, src: Path, start: float, end: float, out: Path) -> float:
    duration = max(0.05, end - start)
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{max(0.0, start):.3f}", "-t", f"{duration:.3f}",
        "-i", str(src), "-vn", "-c:a", "libmp3lame", "-q:a", "2",
        "-write_xing", "1", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    container = av.open(str(out))
    actual = float(container.duration) / av.time_base
    container.close()
    return actual


def copy_audio_indexed(src: Path, dst: Path, ffmpeg: str) -> None:
    """复制整段音频时补上 Xing/Info 头。

    源 MP3 多半没有 Xing 头，浏览器只能按码率估时长（实测 1546.24 秒被估成
    1543.93 秒），按时间 seek 会整体偏移 1–2 秒，表现为句首被吞、句尾多出下一句。
    这里无损重封装（-c:a copy）并写入 Xing 头；不是 MP3 时退回普通复制。
    """
    try:
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(src), "-map", "0:a:0", "-c:a", "copy",
             "-map_metadata", "-1", "-write_xing", "1",
             "-id3v2_version", "0", "-write_id3v1", "0", str(dst)],
            check=True, capture_output=True)
    except Exception:
        shutil.copy2(src, dst)


def safe_stem(name: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*]+', "_", name).strip(" .")
    return stem or "听力材料"


def unique_dir(base: Path, stem: str) -> Path:
    candidate = base / stem
    if not candidate.exists():
        return candidate
    for i in range(2, 100):
        candidate = base / f"{stem}-{i}"
        if not candidate.exists():
            return candidate
    return base / f"{stem}-{int(time.time())}"


LLM_SYSTEM = "你是严谨的英语听力精听助手。你只输出 JSON，不输出解释或 Markdown。"

LLM_PROMPT_HEAD = """下面是一个英语听力题型单元的正文和题目转写（ASR 结果）。
请完成：
1. 把正文拆成完整句子。要求：逐字复制；允许修正明显的 ASR 重复词和同音误识别；不得改写、概括、遗漏；不要包含 "Conversation one" / "Recording one" 这类标题。
2. 题目按 Question 编号输出，去掉 "Question N." 前缀；题目说明（Questions 9 to 11 are based on...）不要当成题目。
3. 只输出 JSON，格式：
{"sentences":["..."],"questions":[{"number":9,"text":"..."}]}
"""


def load_llm_config(model_override: str = "") -> Optional[dict]:
    env = dict(os.environ)
    if not (env.get("ANTHROPIC_BASE_URL") and env.get("ANTHROPIC_AUTH_TOKEN")):
        settings = Path.home() / ".claude" / "settings.json"
        if settings.exists():
            try:
                data = json.loads(settings.read_text(encoding="utf-8"))
                for k, v in (data.get("env") or {}).items():
                    env.setdefault(k, v)
            except Exception:
                pass
    base = env.get("ANTHROPIC_BASE_URL")
    token = env.get("ANTHROPIC_AUTH_TOKEN")
    model = (
        model_override
        or env.get("ANTHROPIC_MODEL")
        or env.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
    )
    if not (base and token and model):
        return None
    return {"base_url": base, "auth_token": token, "model": model}


def parse_json_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        return json.loads(text[i:j + 1])
    raise ValueError("模型输出里没有 JSON")


def align_one(text: str, words: list[Word], cursor: int = 0,
              search_ahead: int = 120) -> Optional[tuple]:
    target = [
        t for t in (
            norm_word(x) for x in re.findall(r"[A-Za-z0-9']+", text.lower())
        ) if t
    ]
    if not target or not words:
        return None
    n = len(target)
    best = None
    max_start = min(len(words), cursor + n * 2 + search_ahead)
    for start in range(cursor, max_start):
        for extra in range(-3, 7):
            m = n + extra
            if m < 1 or start + m > len(words):
                continue
            window = [norm_word(w.text) for w in words[start:start + m]]
            ratio = difflib.SequenceMatcher(
                None, target, window, autojunk=False
            ).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, start, start + m - 1)
    if best and best[0] >= 0.5:
        return best
    return None


def align_sentences(texts: list[str], words: list[Word], label: str,
                    warnings: list[str]) -> Optional[list[dict]]:
    cursor = 0
    out = []
    matched = 0
    for idx, text in enumerate(texts, 1):
        r = align_one(text, words, cursor)
        if not r:
            warnings.append(
                f"{label} 第 {idx} 句模型文本与转写对不上，已回退规则切分。"
            )
            return None
        ratio, start, end = r
        out.append({
            "i": idx,
            "start": round(words[start].start, 3),
            "end": round(words[end].end, 3),
            "en": text.strip(),
            "align": round(ratio, 2),
        })
        cursor = end + 1
        matched += end - start + 1
    if not out:
        return None
    coverage = min(1.0, matched / max(1, len(words)))
    if coverage < 0.75:
        warnings.append(
            f"{label} 模型句子只覆盖正文的 {coverage:.0%}，已回退规则切分。"
        )
        return None
    return out


def add_review_flags(sentences: list[dict]) -> list[dict]:
    for s in sentences:
        reasons = []
        if s["end"] - s["start"] > 20:
            reasons.append("超过20秒")
        if len(re.findall(r"[A-Za-z0-9']+", s["en"])) > 30:
            reasons.append("超过30词")
        if not s["en"].rstrip().endswith((".", "?", "!", "。", "？", "！")):
            reasons.append("句末无标点")
        if s.get("align", 1.0) < 0.75:
            reasons.append("对齐相似度低")
        s["review"] = bool(reasons)
        s["review_reasons"] = reasons
    return sentences


def heuristic_question_items(raw: dict, flat: list[Word],
                             questions: list[Event]) -> list[dict]:
    qstart, qend = raw["questions_start"], raw["questions_end"]
    if qend <= qstart + 0.5:
        return []
    qs = [q for q in questions if qstart - 0.1 <= q.time < qend]
    qs = dedup_events(qs, lambda e: e.number, 1.0)
    out = []
    for j, q in enumerate(qs):
        qe = qs[j + 1].time if j + 1 < len(qs) else qend
        out.append({
            "i": j + 1,
            "number": q.number,
            "start": round(q.time, 3),
            "end": round(qe, 3),
            "en": text_between(flat, q.time, qe),
        })
    if not out:
        out.append({
            "i": 1,
            "number": 0,
            "start": round(qstart, 3),
            "end": round(qend, 3),
            "en": text_between(flat, qstart, qend),
        })
    return out


def llm_split_item(client, model: str, raw: dict, flat: list[Word],
                   label: str, max_tokens: int = 16000) -> Optional[dict]:
    content_text = text_between(flat, raw["content_start"], raw["content_end"])
    question_text = ""
    if raw["questions_end"] > raw["questions_start"] + 0.5:
        question_text = text_between(
            flat, raw["questions_start"], raw["questions_end"]
        )
    if not content_text.strip():
        return None
    prompt = (
        LLM_PROMPT_HEAD
        + "\n正文：\n" + content_text
        + "\n\n题目：\n" + (question_text or "（无）")
        + "\n\n只输出 JSON。"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=LLM_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(
        getattr(b, "text", "")
        for b in resp.content
        if getattr(b, "type", "") == "text"
    ).strip()
    if not text:
        return None
    obj = parse_json_text(text)
    sentences = [
        str(x).strip() for x in (obj.get("sentences") or []) if str(x).strip()
    ]
    questions = []
    for q in (obj.get("questions") or []):
        if not isinstance(q, dict):
            continue
        qt = str(q.get("text") or "").strip()
        if not qt:
            continue
        try:
            num = int(q.get("number") or 0)
        except Exception:
            num = 0
        questions.append({"number": num, "text": qt})
    if not sentences:
        return None
    return {"sentences": sentences, "questions": questions}


def make_item_from_llm(raw: dict, flat: list[Word], questions: list[Event],
                       llm: dict, index: int, warnings: list[str],
                       label: str) -> Optional[dict]:
    cwords = words_between(flat, raw["content_start"], raw["content_end"])
    if not cwords:
        return None
    sentences = align_sentences(llm["sentences"], cwords, label, warnings)
    if sentences is None:
        return None

    qitems = []
    qwords = (
        words_between(flat, raw["questions_start"], raw["questions_end"])
        if raw["questions_end"] > raw["questions_start"] + 0.5 else []
    )
    if qwords and llm["questions"]:
        cursor = 0
        for j, q in enumerate(llm["questions"], 1):
            r = align_one(q["text"], qwords, cursor, search_ahead=120)
            if not r:
                qitems = []
                warnings.append(
                    f"{label} 第 {j} 题模型文本与转写对不上，题目时间改用规则切分。"
                )
                break
            ratio, start, end = r
            qitems.append({
                "i": j,
                "number": q["number"] or j,
                "start": round(qwords[start].start, 3),
                "end": round(qwords[end].end, 3),
                "en": q["text"],
            })
            cursor = end + 1
    if not qitems:
        qitems = heuristic_question_items(raw, flat, questions)

    sentences = add_review_flags(sentences)
    kind = raw["kind"]
    number = raw["number"]
    title = f"{KIND_TITLE.get(kind, 'Item')} {number}" if number else KIND_TITLE.get(kind, "Item")
    return {
        "index": index,
        "title": title,
        "kind": kind,
        "number": number,
        "content": {
            "start": round(max(0.0, sentences[0]["start"] - 0.2), 3),
            "end": round(sentences[-1]["end"] + 0.2, 3),
        },
        "questions": {
            "start": round(raw["questions_start"], 3),
            "end": round(raw["questions_end"], 3),
        },
        "sentences": sentences,
        "question_items": qitems,
        "llm": True,
    }


def make_item_dict(raw: dict, flat: list[Word], questions: list[Event],
                   index: int) -> dict:
    cstart, cend = raw["content_start"], raw["content_end"]
    cwords = words_between(flat, cstart, cend)
    if cwords:
        cstart = max(cstart, cwords[0].start - 0.2)
        cend = min(cend, cwords[-1].end + 0.2)

    sentences = []
    for i, sent in enumerate(split_sentences(cwords), 1):
        sentences.append({
            "i": i,
            "start": round(sent[0].start, 3),
            "end": round(sent[-1].end, 3),
            "en": join_words(sent),
            "align": 1.0,
        })

    qitems = heuristic_question_items(raw, flat, questions)
    qstart, qend = raw["questions_start"], raw["questions_end"]
    sentences = add_review_flags(sentences)

    kind = raw["kind"]
    number = raw["number"]
    title = f"{KIND_TITLE.get(kind, 'Item')} {number}" if number else KIND_TITLE.get(kind, "Item")
    return {
        "index": index,
        "title": title,
        "kind": kind,
        "number": number,
        "content": {"start": round(cstart, 3), "end": round(cend, 3)},
        "questions": {"start": round(qstart, 3), "end": round(qend, 3)},
        "sentences": sentences,
        "question_items": qitems,
        "llm": False,
    }


def section_label(letter: str, items: list[dict]) -> str:
    kinds = {i["kind"] for i in items if i["kind"]}
    if "conversation" in kinds:
        suffix = "长对话"
    elif "passage" in kinds:
        suffix = "短文理解"
    elif "recording" in kinds or "lecture" in kinds or "talk" in kinds:
        suffix = "讲座/讲话"
    elif "news report" in kinds:
        suffix = "新闻报道"
    else:
        suffix = ""
    base = f"Section {letter}" if letter != "未分类" else "未分类"
    return f"{base} {suffix}".strip()


def refresh_paper_index(out_base: Path) -> Path:
    """扫描 out_base 下的试卷目录，写入工作台读取的 试卷索引.js。"""
    entries = []
    for d in out_base.iterdir():
        if not d.is_dir():
            continue
        data_js = d / "data.js"
        if not data_js.is_file():
            continue
        title = d.name
        created_at = ""
        paper_id = ""
        duration = 0.0
        stats: dict = {}
        timeline = d / "时间轴.json"
        try:
            if timeline.is_file():
                meta = json.loads(timeline.read_text(encoding="utf-8"))
                title = meta.get("title") or title
                created_at = meta.get("created_at") or ""
                paper_id = meta.get("paper_id") or ""
                duration = meta.get("duration") or 0.0
                # 句数/单元数从 sections 现算，别信可能过期的 stats 字段
                sections = meta.get("sections") or []
                stats = {
                    "items": sum(len(s.get("items") or []) for s in sections),
                    "sentences": sum(len(it.get("sentences") or [])
                                     for s in sections for it in (s.get("items") or [])),
                }
        except Exception:
            pass
        mtime = data_js.stat().st_mtime
        entries.append({
            "dir": d.name,
            "title": title,
            "paper_id": paper_id,
            "created_at": created_at,
            "duration": duration,
            "stats": stats,
            "_mtime": mtime,
        })
    entries.sort(key=lambda e: (e["created_at"], e["_mtime"], e["dir"]), reverse=True)
    for e in entries:
        e.pop("_mtime", None)

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = (
        "window.PAPERS = " + json.dumps(entries, ensure_ascii=False, indent=2) + ";\n"
        "window.PAPERS_UPDATED_AT = " + json.dumps(updated_at, ensure_ascii=False) + ";\n"
    )
    target = out_base / "试卷索引.js"
    tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    return target


def install_workbench(dest: Path) -> Path | None:
    """构建并复制唯一的工作台文件；dest 可以是 html 路径或目录。"""
    dest = dest.expanduser().resolve()
    if dest.suffix.lower() not in (".html", ".htm"):
        dest = dest / "精听工作台.html"
    if dest == TEMPLATE.resolve():
        print(f"警告：工作台目标与构建产物是同一个文件：{dest}")
        return None
    try:
        import build_workbench
        build_workbench.ensure_built()
    except Exception as exc:
        print(f"警告：工作台构建失败：{exc}")
        print("      未复制旧产物，避免部署过期界面。")
        return None
    if not TEMPLATE.exists():
        print(f"警告：工作台构建产物不存在：{TEMPLATE}")
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATE, dest)
    except PermissionError:
        print(f"警告：无法写入工作台（文件可能被浏览器占用）：{dest}")
        print("      关闭已打开的工作台标签页后重试。")
        return None
    print(f"工作台已部署：{dest}")
    return dest


def write_outputs(audio_path: Path, out_root: Path, paper: dict,
                  flat: list[Word], questions: list[Event],
                  ffmpeg: str, snap: bool = True) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    audio_dst = out_root / "audio.mp3"
    if audio_path.resolve() != audio_dst.resolve():
        copy_audio_indexed(audio_path, audio_dst, ffmpeg)

    # 句尾吸附：whisper 的 word.end 偏早 0.19s（中位），不修会切掉尾音。
    # 只动句尾、不动句首，与批量修旧卷用同一实现（audio_snap.snap_ends）。
    if snap:
        try:
            pauses = detect_silences(audio_path, ffmpeg)
        except Exception as exc:
            print(f"  句尾吸附：静音检测失败，跳过（{exc}）", flush=True)
        else:
            if pauses:
                changed = snap_ends(paper, pauses)
                print(f"  句尾吸附：改 {changed} 句（静音段 {len(pauses)} 个）", flush=True)
            else:
                print("  句尾吸附：未检测到静音段，跳过", flush=True)
    else:
        print("  句尾吸附：已按 --no-snap 关闭", flush=True)

    total_sentences = 0
    total_items = 0
    for sec in paper["sections"]:
        sec_slug = re.sub(r'[\\/:*?"<>|]+', "-", sec["name"])
        sec_slug = re.sub(r"\s+", "-", sec_slug)
        for item in sec["items"]:
            total_items += 1
            item_slug = f"{item['index']:02d}-{item['title'].replace(' ', '-')}"
            item_dir = out_root / sec_slug / item_slug
            (item_dir / "句子").mkdir(parents=True, exist_ok=True)

            content_start = max(0.0, item["content"]["start"] - 0.2)
            content_end = item["content"]["end"] + 0.2
            content_file = item_dir / "正文.mp3"
            cut_audio(ffmpeg, audio_path, content_start, content_end, content_file)

            questions_file = None
            qstart, qend = item["questions"]["start"], item["questions"]["end"]
            if qend > qstart + 0.5:
                (item_dir / "问题").mkdir(exist_ok=True)
                questions_file = item_dir / "题目.mp3"
                cut_audio(ffmpeg, audio_path, qstart, qend, questions_file)
                for q in item["question_items"]:
                    qf = item_dir / "问题" / f"{q['i']:02d}.mp3"
                    cut_audio(ffmpeg, audio_path, max(0.0, q["start"] - 0.1),
                              q["end"] + 0.1, qf)

            for k, sent in enumerate(item["sentences"]):
                if k + 1 < len(item["sentences"]):
                    next_start = item["sentences"][k + 1]["start"]
                    end = max(sent["end"], min(sent["end"] + 0.35, next_start))
                else:
                    end = sent["end"] + 0.2
                sf = item_dir / "句子" / f"{sent['i']:02d}.mp3"
                cut_audio(ffmpeg, audio_path, max(0.0, sent["start"] - 0.2), end, sf)
                total_sentences += 1

            item["paths"] = {
                "content": str(content_file.relative_to(out_root)).replace("\\", "/"),
                "questions": (
                    str(questions_file.relative_to(out_root)).replace("\\", "/")
                    if questions_file else ""
                ),
            }
            print(
                f"  完成：{sec['name']} / {item['title']} "
                f"（{len(item['sentences'])} 句，{fmt_short(item['content']['start'])}–"
                f"{fmt_short(item['content']['end'])}）"
            )

    paper["stats"] = {"items": total_items, "sentences": total_sentences}

    with open(out_root / "时间轴.json", "w", encoding="utf-8") as f:
        json.dump(paper, f, ensure_ascii=False, indent=2)

    (out_root / "data.js").write_text(
        "window.PAPER = " + json.dumps(paper, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )

    lines = [
        f"# {paper['title']} · 听力分割目录",
        "",
        f"- 源音频：`{paper['source_audio']}`",
        f"- 总时长：{fmt_short(paper['duration'])}",
        f"- 生成时间：{paper['created_at']}",
        f"- ASR 模型：`{paper['model']}`",
        f"- 切分方式：{paper.get('mode', 'rules')}（{paper.get('llm_model', '规则模式')}）",
        f"- 题型单元：{total_items} 段；逐句：{total_sentences} 句",
        "",
        "| Section | 题型 | 正文范围 | 句子数 | 待校对 | 正文文件 | 题目文件 |",
        "|---|---|---|---|---|---|---|",
    ]
    for sec in paper["sections"]:
        for item in sec["items"]:
            review_n = sum(1 for s in item["sentences"] if s.get("review"))
            lines.append(
                f"| {sec['name']} | {item['title']} | "
                f"{fmt_short(item['content']['start'])}–{fmt_short(item['content']['end'])} | "
                f"{len(item['sentences'])} | {review_n} | `{item['paths']['content']}` | "
                f"{'`' + item['paths']['questions'] + '`' if item['paths']['questions'] else '—'} |"
            )
    if paper.get("warnings"):
        lines += ["", "## 识别提示", ""]
        lines += [f"- {w}" for w in paper["warnings"]]
    lines += [
        "",
        "## 怎么用",
        "",
        "1. 打开项目里的 `工作台\\精听工作台.html`，在顶部下拉框选择本试卷。",
        "2. 左侧按 Section 和题型切换；每段正文、题目、逐句音频都在对应文件夹里。",
        "3. 如果某句切点不准，可在工作台里点“设起点”手动覆盖。",
        "4. “待校对”表示该句超过 20 秒、超过 30 词、句末无标点或对齐相似度低；"
        "在工作台里点“只看待校对”逐句检查即可。",
    ]
    (out_root / "目录.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 转写与主流程
def load_transcript(path: Path) -> tuple[dict, list[Segment], float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segs = []
    for s in data["segments"]:
        words = [
            Word(float(w["start"]), float(w["end"]), w["word"])
            for w in s.get("words", [])
        ]
        segs.append(Segment(float(s["start"]), float(s["end"]), s["text"], words))
    duration = float(data.get("duration") or (segs[-1].end if segs else 0.0))
    return data, segs, duration


def transcribe(audio: Path, model_path: str, language: str,
               out_dir: Path) -> tuple[dict, list[Segment], float]:
    print(f"加载模型：{model_path}", flush=True)
    threads = int(os.environ.get("CET6_THREADS", "0") or 0)
    model = WhisperModel(model_path, device="cpu", compute_type="int8",
                         cpu_threads=threads)
    print("开始转写（CPU，base.en 约 5–10 倍速）……", flush=True)
    t0 = time.time()
    segments_iter, info = model.transcribe(
        str(audio),
        language=language,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    data = {
        "audio": str(audio),
        "language": info.language,
        "duration": round(info.duration, 3),
        "segments": [],
    }
    for idx, seg in enumerate(segments_iter, 1):
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word}
            for w in (seg.words or [])
        ]
        data["segments"].append({
            "id": seg.id,
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": words,
        })
        if idx % 25 == 0:
            print(f"  已转写 {idx} 段，进度 {fmt_short(seg.end)} / "
                  f"{fmt_short(info.duration)}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"转写完成：{len(data['segments'])} 段，用时 {time.time() - t0:.0f} 秒", flush=True)
    segs = [
        Segment(
            float(s["start"]), float(s["end"]), s["text"],
            [Word(float(w["start"]), float(w["end"]), w["word"]) for w in s["words"]],
        )
        for s in data["segments"]
    ]
    return data, segs, float(data["duration"])


def main() -> int:
    parser = argparse.ArgumentParser(description="通用英语听力分割器")
    parser.add_argument("audio", nargs="?", help="音频文件路径（--refresh-index 时可省略）")
    parser.add_argument("--out", default="", help="输出根目录（默认：工具目录/输出）")
    parser.add_argument("--model", default="", help="Whisper 模型名或本地路径")
    parser.add_argument("--language", default="en", help="语言，默认 en")
    parser.add_argument("--transcript", default="", help="已有 transcript.json，跳过转写")
    parser.add_argument("--no-llm", action="store_true", help="关闭模型判断，只用规则切分")
    parser.add_argument("--llm-model", default="", help="覆盖模型名，例如 deepseek-v4-pro[1M]")
    parser.add_argument("--llm-max-tokens", type=int, default=16000,
                        help="模型单次最大输出 token，默认 16000")
    parser.add_argument("--workbench", default="",
                        help="按需构建并部署工作台到指定路径（目录或 html）")
    parser.add_argument("--refresh-index", action="store_true",
                        help="只刷新 试卷索引.js，不处理音频")
    parser.add_argument("--no-snap", action="store_true",
                        help="关闭句尾静音吸附（默认开启）")
    args = parser.parse_args()

    out_base = Path(args.out).expanduser().resolve() if args.out else TOOL_DIR.parent / "输出"
    out_base.mkdir(parents=True, exist_ok=True)

    if args.refresh_index:
        idx = refresh_paper_index(out_base)
        print(f"索引：{idx}")
        if args.workbench:
            wb = install_workbench(Path(args.workbench))
            if wb:
                print(f"工作台：{wb}")
        return 0

    if not args.audio:
        parser.error("缺少音频文件（或用 --refresh-index 只刷新索引）")

    audio = Path(args.audio).expanduser().resolve()
    if not audio.exists():
        print(f"失败：找不到音频文件：{audio}")
        return 1

    out_root = unique_dir(out_base, safe_stem(audio.stem))

    model_path = args.model or (str(DEFAULT_MODEL) if DEFAULT_MODEL.exists() else "base.en")
    print(f"音频：{audio}")
    print(f"输出：{out_root}")
    print(f"模型：{model_path}")

    if args.transcript:
        data, segs, duration = load_transcript(Path(args.transcript).resolve())
        print(f"使用已有转写：{args.transcript}（{len(segs)} 段）")
    else:
        data, segs, duration = transcribe(audio, model_path, args.language, out_root)

    if not segs:
        print("失败：没有识别到任何语音段。")
        return 1

    flat = [w for seg in segs for w in seg.words]
    flat.sort(key=lambda w: w.start)

    warnings: list[str] = []
    sections, section_items, qblocks, questions, end_time, _ = build_structure(
        segs, duration, warnings
    )
    print(
        f"识别到 {len(sections)} 个 Section，{len(qblocks)} 个题目块，"
        f"{len(questions)} 道题。"
    )

    llm_cfg = None
    client = None
    if args.no_llm:
        print("已关闭模型判断，使用规则模式。")
    elif Anthropic is None:
        print("未安装 anthropic SDK，使用规则模式。")
    else:
        llm_cfg = load_llm_config(args.llm_model)
        if llm_cfg:
            client = Anthropic(
                base_url=llm_cfg["base_url"],
                auth_token=llm_cfg["auth_token"],
            )
            print(f"模型判断：{llm_cfg['model']}（逐段拆句，失败自动回退规则）")
        else:
            print("未找到模型凭证，使用规则模式。")

    paper_sections = []
    for sec in sections:
        raw_items = section_items.get(id(sec), [])
        if not raw_items:
            continue
        raw_items.sort(key=lambda x: x["content_start"])
        # 同题型内去重编号
        seen: set[tuple[str, int]] = set()
        for item in raw_items:
            kind = item["kind"] or "item"
            num = item["number"]
            if num <= 0 or (kind, num) in seen:
                n = 1
                while (kind, n) in seen:
                    n += 1
                item["number"] = n
            seen.add((kind, item["number"]))

        made = []
        llm_used = 0
        for idx, raw in enumerate(raw_items, 1):
            label = f"{sec.section} / {raw['kind'] or 'Item'} {raw['number']}"
            item = None
            if client:
                print(f"  模型判断：{label} ……", flush=True)
                try:
                    llm = llm_split_item(
                        client, llm_cfg["model"], raw, flat, label,
                        args.llm_max_tokens,
                    )
                    if llm:
                        item = make_item_from_llm(
                            raw, flat, questions, llm, idx, warnings, label
                        )
                except Exception as e:
                    warnings.append(
                        f"{label} 模型调用失败：{e}，已回退规则切分。"
                    )
                    print(f"    模型调用失败，回退规则：{e}")
            if item is None:
                if client:
                    warnings.append(f"{label} 模型结果不可用，已回退规则切分。")
                item = make_item_dict(raw, flat, questions, idx)
            else:
                llm_used += 1
            if item["sentences"]:
                made.append(item)
            else:
                warnings.append(f"{sec.section} 段 {raw['kind']} {raw['number']} 没有切出句子，已跳过。")
        if client:
            print(f"  {sec.section} 段：模型成功 {llm_used} / {len(raw_items)} 段")
        if not made:
            continue
        paper_sections.append({
            "letter": sec.section,
            "name": section_label(sec.section, made),
            "start": round(sec.time, 3),
            "end": round(sec.end_time, 3),
            "items": made,
        })

    if not paper_sections:
        print("失败：没有生成任何可用的题型单元。")
        return 1

    paper = {
        "paper_id": f"{safe_stem(audio.stem)}_{int(duration)}",
        "title": audio.stem,
        "source_audio": str(audio),
        "audio": "audio.mp3",
        "duration": round(duration, 3),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": str(model_path),
        "llm_model": llm_cfg["model"] if llm_cfg else "规则模式",
        "mode": "llm" if llm_cfg else "rules",
        "warnings": warnings,
        "sections": paper_sections,
    }

    # 人工校对过的原文：重切同一份音频时自动套用，避免新产物把校对冲掉。
    fixed = apply_transcript_fixes(paper)
    if fixed:
        print(f"原文校对：应用 {len(fixed)} 处（来源：校对\\{paper['title']}.json）")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    print("开始切音频……", flush=True)
    write_outputs(audio, out_root, paper, flat, questions, ffmpeg,
                  snap=not args.no_snap)

    idx = refresh_paper_index(out_base)
    print("")
    print(f"完成：{out_root}")
    print(f"  目录：{out_root / '目录.md'}")
    print(f"  时间轴：{out_root / '时间轴.json'}")
    print(f"  索引：{idx}")
    if args.workbench:
        wb = install_workbench(Path(args.workbench))
        if wb:
            print(f"  工作台：{wb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
