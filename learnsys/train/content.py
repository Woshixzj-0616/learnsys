"""训练内容包：加载、版本、单句派生。

内容即代码：JSON 进仓库，改动可 diff、可校验。
- `writing.json`：12 篇写作内容包
- `translation.json`：12 篇翻译内容包（含逐句切分）
- `sentences.json`：技能专项单句（60 句）

一句一译的“从篇目拆出的单句”**不另存一份**：直接由 translation 的
`segments` 派生，避免同一句中文出现两个版本。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from functools import lru_cache

CONTENT_DIR = pathlib.Path(__file__).resolve().with_name("content")

SKILLS = (
    "断句意群", "主干识别", "语序调整", "长句拆分", "词性转换",
    "增补省译", "文化术语", "数字比较", "无主句", "指代一致",
)


def _read(path: pathlib.Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError(f"{path.name} 必须是含 items 数组的 JSON 对象")
    return data


def version_of(pack: dict) -> str:
    """内容包版本：内容变了版本就变，批改结果可追溯。"""
    payload = json.dumps(pack, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=8)
def _load_dir(raw_dir: str) -> dict:
    base = pathlib.Path(raw_dir)
    writing = _read(base / "writing.json")["items"]
    translation = _read(base / "translation.json")["items"]
    extra = _read(base / "sentences.json")["items"]
    for item in writing:
        item["kind"] = "writing"
        item["content_version"] = version_of(item)
    for item in translation:
        item["kind"] = "translation"
        item["content_version"] = version_of(item)
    return {
        "writing": writing,
        "translation": translation,
        "extra_sentences": extra,
        "version": hashlib.sha1(
            "|".join(item["content_version"]
                     for item in writing + translation).encode("utf-8")
        ).hexdigest()[:12],
    }


def library(dir_path: pathlib.Path | str | None = None) -> dict:
    return _load_dir(str(pathlib.Path(dir_path or CONTENT_DIR).resolve()))


def writing_items(dir_path=None) -> list[dict]:
    return library(dir_path)["writing"]


def translation_items(dir_path=None) -> list[dict]:
    return library(dir_path)["translation"]


def extra_sentences(dir_path=None) -> list[dict]:
    return library(dir_path)["extra_sentences"]


def pack(kind: str, prompt_id: str, dir_path=None) -> dict | None:
    if kind not in ("writing", "translation"):
        return None
    for item in library(dir_path)[kind]:
        if item.get("id") == prompt_id:
            return item
    return None


def _points_zh(pack_item: dict, ids: list[str]) -> list[str]:
    table = {row.get("id"): row.get("zh", "")
             for row in pack_item.get("info_points") or []}
    return [table[key] for key in ids if table.get(key)]


def derived_sentences(dir_path=None) -> list[dict]:
    """由翻译篇目的 segments 派生单句；id 形如 `t05-s3`。"""
    rows: list[dict] = []
    for item in translation_items(dir_path):
        variants = {}
        for row in item.get("variants") or []:
            try:
                variants[int(row.get("segment"))] = list(row.get("options") or [])
            except (TypeError, ValueError):
                continue
        for index, seg in enumerate(item.get("segments") or [], start=1):
            info_ids = list(seg.get("info_points") or [])
            rows.append({
                "id": f"{item['id']}-s{index}",
                "skill": str(seg.get("skill") or ""),
                "zh": str(seg.get("zh") or ""),
                "reference": str(seg.get("reference") or ""),
                "variants": variants.get(index, []),
                "keywords": list(seg.get("keywords") or []),
                "skeleton": str(seg.get("skeleton") or ""),
                "info_points": _points_zh(item, info_ids),
                "source_id": item["id"],
                "source_title": item.get("title", ""),
                "origin": "passage",
            })
    return rows


def sentence_items(dir_path=None) -> list[dict]:
    """一句一译题库：篇目派生句 + 技能专项句（专项句在前）。"""
    rows = []
    for item in extra_sentences(dir_path):
        row = dict(item)
        row.setdefault("variants", [])
        row.setdefault("keywords", [])
        row.setdefault("info_points", [])
        row.setdefault("source_id", "")
        row.setdefault("source_title", "技能专项")
        row["origin"] = "skill"
        rows.append(row)
    rows.extend(derived_sentences(dir_path))
    return rows


def sentence(sentence_id: str, dir_path=None) -> dict | None:
    for row in sentence_items(dir_path):
        if row.get("id") == sentence_id:
            return row
    return None


def all_packs(dir_path=None) -> list[dict]:
    lib = library(dir_path)
    return list(lib["writing"]) + list(lib["translation"])
