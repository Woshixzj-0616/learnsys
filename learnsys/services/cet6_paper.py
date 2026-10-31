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
