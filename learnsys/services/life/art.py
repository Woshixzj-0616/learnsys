"""创作库：图片路径安全、豆包文本导入、作品建档。

图片只接受 `DATA_ROOT` 内的 png/jpg/jpeg/webp/gif（先走 `/api/upload`）；
导入文本按「标签优先、无标签按首行标题」解析，风格名自动匹配或新建。
"""
from __future__ import annotations

import pathlib
import re

from learnsys import config, store

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_IMPORT_BLOCKS = 20
TITLE_CAP = 60
LABELS = {"标题": "title", "提示词": "prompt", "提示": "prompt",
          "风格": "style", "模型": "model", "备注": "note"}
_LABEL_RE = re.compile(r"^(标题|提示词|提示|风格|模型|备注)\s*[:：]\s*(.*)$")


def safe_image_path(work: dict) -> pathlib.Path | None:
    """返回可回显的图片路径；不在数据目录 / 不是图片 / 不存在都返回 None。"""
    raw = str((work or {}).get("file_path") or "").strip()
    if not raw:
        return None
    path = pathlib.Path(raw)
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    try:
        root = pathlib.Path(config.DATA_ROOT).resolve()
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def validate_work(title: str, file_path: str = "") -> None:
    if not str(title or "").strip():
        raise ValueError("作品标题不能为空")
    raw = str(file_path or "").strip()
    if not raw:
        return
    if pathlib.Path(raw).suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("图片只支持 png / jpg / webp / gif")
    try:
        root = pathlib.Path(config.DATA_ROOT).resolve()
        pathlib.Path(raw).resolve().relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("图片要先上传到工作台（只接受数据目录内的图片）") from exc


def parse_import(text: str) -> list[dict]:
    """把豆包导出的文本切成作品块；标签优先，无标签按首行标题。"""
    raw = str(text or "").replace("\r\n", "\n").strip()
    if not raw:
        raise ValueError("导入文本不能为空")
    blocks = [block.strip() for block in re.split(r"\n\s*\n", raw)
              if block.strip()][:MAX_IMPORT_BLOCKS]
    items: list[dict] = []
    for block in blocks:
        data = {"title": "", "prompt": "", "style": "", "model": "", "note": ""}
        extra: list[str] = []
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            match = _LABEL_RE.match(line)
            if match:
                key = LABELS[match.group(1)]
                value = match.group(2).strip()
                if key == "prompt" and data["prompt"]:
                    data["prompt"] += "\n" + value
                else:
                    data[key] = value
            else:
                extra.append(line)
        if not data["title"]:
            data["title"] = extra.pop(0)[:TITLE_CAP] if extra else "未命名作品"
        if not data["prompt"]:
            data["prompt"] = "\n".join(extra)
        items.append(data)
    return items


def import_works(conn, text: str) -> list[dict]:
    """解析并落库；风格名命中已有预设就复用，没有就建一个空预设。"""
    items = parse_import(text)
    works: list[dict] = []
    for item in items:
        preset_id = 0
        style = str(item.get("style") or "").strip()
        if style:
            preset = store.get_art_preset_by_name(conn, style)
            if preset is None:
                preset = store.upsert_art_preset(conn, name=style)
            preset_id = preset["id"]
        works.append(store.add_art_work(
            conn, title=item["title"], prompt=item["prompt"],
            preset_id=preset_id, model=item["model"], note=item["note"]))
    return works
