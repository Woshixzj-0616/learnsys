"""六级试卷 data.js 的唯一读取入口：题干、段落结构与音频路径。

试卷目录里的 `data.js` 是分割工具产出的真相源；这里只做解析和路径还原，
**不把题干复制进数据库**，避免出现第二份会漂移的副本。

目录约定（与 `routes_cet6.mount_static` 的挂载点一致）：
`<cet6_dir>/试卷/<paper_title>/data.js`，音频通过 `/cet6/试卷/...` 暴露。
"""
from __future__ import annotations

import json
import pathlib
import urllib.parse

from learnsys import config

# (data.js 绝对路径, mtime_ns, size) -> 解析结果；试卷文件运行期不变。
_CACHE: dict[tuple[str, int, int], dict] = {}
_MAX_CACHE = 8
# transcript.json 更大（约 350 KB），单独一份小缓存给词级时间轴。
_TR_CACHE: dict[tuple[str, int, int], list[tuple[float, float, str]]] = {}
_MAX_TR_CACHE = 4


class PaperNotFound(LookupError):
    """试卷目录、data.js 或指定段落不存在。"""


def paper_dir(paper_title: str) -> pathlib.Path:
    """按目录名找试卷；DB 的 `paper_id` 就是 `paper_title`，不要用 data.js 的 id。"""
    return config.cet6_dir() / "试卷" / str(paper_title or "")


def load_paper(paper_title: str) -> dict:
    """读取并解析 `window.PAPER = {...}`；按文件 mtime 缓存。"""
    path = paper_dir(paper_title) / "data.js"
    try:
        stat = path.stat()
    except OSError as exc:
        raise PaperNotFound(f"找不到试卷数据：{paper_title}") from exc
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        text = path.read_text(encoding="utf-8-sig")
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("没有对象")
        data = json.loads(text[start:end + 1])
    except (OSError, ValueError) as exc:
        raise PaperNotFound(f"试卷数据读不出来：{paper_title}") from exc
    if not isinstance(data, dict):
        raise PaperNotFound(f"试卷数据格式不对：{paper_title}")
    if len(_CACHE) >= _MAX_CACHE:
        _CACHE.clear()
    _CACHE[key] = data
    return data


def _section_matches(section: dict, name: str) -> bool:
    return str(section.get("name") or "") == name


def find_item(paper_title: str, section: str, item: str) -> tuple[dict, dict]:
    """按 DB 里的 `section` / `item` 文本定位段落；找不到抛 `PaperNotFound`。"""
    data = load_paper(paper_title)
    for sec in data.get("sections") or []:
        if not isinstance(sec, dict) or not _section_matches(sec, str(section or "")):
            continue
        for entry in sec.get("items") or []:
            if isinstance(entry, dict) and str(entry.get("title") or "") == str(item or ""):
                return sec, entry
    raise PaperNotFound(f"试卷里没有这一段：{section} / {item}")


def _relative_path(entry: dict, part: str) -> str:
    """优先用 data.js 自带的相对路径；老数据没有 paths 时按目录规则还原。"""
    paths = entry.get("paths") or {}
    value = str(paths.get(part) or "").strip()
    if value:
        return value.replace("\\", "/")
    return ""


def _fallback_item_dir(section: str, item: str) -> str:
    section_dir = (str(section or "").replace("Section ", "Section-")
                   .replace(" ", "-").replace("/", "-"))
    item_slug = str(item or "").replace(" ", "-")
    return f"{section_dir}/{item_slug}"


def _url_for_relative(paper_title: str, relative: str) -> str:
    parts = [part for part in str(relative or "").replace("\\", "/").split("/")
             if part]
    quoted = "/".join(urllib.parse.quote(part, safe="") for part in parts)
    return (f"/cet6/{urllib.parse.quote('试卷', safe='')}/"
            f"{urllib.parse.quote(str(paper_title or ''), safe='')}/{quoted}")


def audio_url(paper_title: str, section: str, item: str, *,
              sentence: int | None = None,
              question: int | None = None,
              part: str = "content") -> str:
    """还原一段试卷音频的 URL。

    - `part="content"`：正文.mp3
    - `part="questions"`：题目.mp3（整段题目连播）
    - `question=N`：问题/NN.mp3（单题，NN 是题组内序号，从 1 起）
    - `sentence=N`：句子/NN.mp3（逐句）
    """
    try:
        _, entry = find_item(paper_title, section, item)
    except PaperNotFound:
        return ""
    relative = _relative_path(entry, "content" if part != "questions" else "questions")
    if not relative:
        base = _fallback_item_dir(section, item)
        section_dir, _, item_slug = base.partition("/")
        candidates = sorted(
            (paper_dir(paper_title) / section_dir).glob(f"[0-9][0-9]-{item_slug}"))
        if candidates:
            base = f"{section_dir}/{candidates[0].name}"
        relative = f"{base}/{'正文.mp3' if part != 'questions' else '题目.mp3'}"
    folder = pathlib.PurePosixPath(relative).parent
    if question is not None:
        relative = f"{folder}/问题/{int(question):02d}.mp3"
    elif sentence is not None:
        relative = f"{folder}/句子/{int(sentence):02d}.mp3"
    try:
        exists = (paper_dir(paper_title) / relative).exists()
    except OSError:
        exists = False
    return _url_for_relative(paper_title, relative) if exists else ""


def item_questions(paper_title: str, section: str, item: str) -> list[dict]:
    """把 `question_items` 归一成前端可直接用的列表。

    `number` 是卷面题号（1–25）；`index` 是题组内序号，对应 `问题/NN.mp3`。
    """
    _, entry = find_item(paper_title, section, item)
    result: list[dict] = []
    for position, raw in enumerate(entry.get("question_items") or [], start=1):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("en") or "").strip()
        if not text:
            continue
        try:
            index = int(raw.get("i") or position)
        except (TypeError, ValueError):
            index = position
        try:
            number = int(raw.get("number") or index)
        except (TypeError, ValueError):
            number = index
        result.append({
            "number": number,
            "index": index,
            "en": text,
            "audio_url": audio_url(paper_title, section, item, question=index),
        })
    return result


def item_audio(paper_title: str, section: str, item: str) -> dict:
    """正文 / 整段题目 两个音频 URL；找不到段落时都为空串。"""
    return {
        "content": audio_url(paper_title, section, item, part="content"),
        "questions": audio_url(paper_title, section, item, part="questions"),
    }


def has_audio(paper_title: str, section: str, item: str) -> bool:
    """正文音频真实存在才进队列；没有音频目录时调用方自行降级。"""
    return bool(audio_url(paper_title, section, item, part="content"))


def load_transcript(paper_title: str) -> list[tuple[float, float, str]]:
    """读取 `transcript.json` 的词级时间轴；没有文件返回空列表。

    只保留 (start, end, word)，按时间排序。文件不存在不算错误 ——
    强化刷题卷这类手工卷没有 transcript，意群训练直接跳过。
    """
    path = paper_dir(paper_title) / "transcript.json"
    try:
        stat = path.stat()
    except OSError:
        return []
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _TR_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    words: list[tuple[float, float, str]] = []
    for segment in (data or {}).get("segments") or []:
        if not isinstance(segment, dict):
            continue
        for raw in segment.get("words") or []:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("word") or "").strip()
            if not text:
                continue
            try:
                words.append((float(raw["start"]), float(raw["end"]), text))
            except (KeyError, TypeError, ValueError):
                continue
    words.sort(key=lambda item: item[0])
    if len(_TR_CACHE) >= _MAX_TR_CACHE:
        _TR_CACHE.clear()
    _TR_CACHE[key] = words
    return words


def sentence_entry(paper_title: str, section: str, item: str,
                   sentence: int) -> dict | None:
    """取某一句的 data.js 记录（原文、起止时间）；找不到返回 None。"""
    try:
        _, entry = find_item(paper_title, section, item)
    except PaperNotFound:
        return None
    target = int(sentence or 0)
    for position, raw in enumerate(entry.get("sentences") or [], start=1):
        if not isinstance(raw, dict):
            continue
        try:
            number = int(raw.get("i") or position)
        except (TypeError, ValueError):
            number = position
        if number == target:
            return raw
    return None


def sentence_words(paper_title: str, section: str, item: str,
                   sentence: int) -> dict | None:
    """某句的原文 + 落在它时间范围内的词级时间轴。"""
    entry = sentence_entry(paper_title, section, item, sentence)
    if entry is None:
        return None
    try:
        start = float(entry.get("start"))
        end = float(entry.get("end"))
    except (TypeError, ValueError):
        return None
    text = str(entry.get("en") or "").strip()
    if not text or end <= start:
        return None
    picked = [(w_start, w_end, word) for w_start, w_end, word
              in load_transcript(paper_title)
              if start - 0.08 <= (w_start + w_end) / 2 <= end + 0.08]
    return {"start": start, "end": end, "text": text, "words": picked}
