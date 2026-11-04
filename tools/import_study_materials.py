"""把技能笔记 / 课程文档导入资料库（不是记忆表）。

    .venv/Scripts/python.exe tools/import_study_materials.py --dry-run
    .venv/Scripts/python.exe tools/import_study_materials.py --roots skill --allow-roots
    .venv/Scripts/python.exe tools/import_study_materials.py --roots course --allow-roots

只收 .pdf/.docx/.pptx/.txt/.md；代码、图片、压缩包、旧 .ppt 与 .xlsx 跳过。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config
from learnsys.services import materials_import

SKILL = pathlib.Path(r"D:/cahier/智库/智库/技能")
COURSES = (pathlib.Path(r"D:/Desktop/大一"),
           pathlib.Path(r"D:/Desktop/大二"),
           pathlib.Path(r"D:/Desktop/金融人工智能"))
SUFFIXES = materials_import.SUFFIXES


def _dirs(root: pathlib.Path):
    yield root
    try:
        for path in root.rglob("*"):
            if path.is_dir() and not any(
                    part in materials_import.SKIP_DIRS for part in path.parts):
                yield path
    except OSError:
        return


def _count(root: pathlib.Path) -> dict:
    stats = {"files": 0, "bytes": 0, "by_suffix": {}}
    for folder in _dirs(root):
        try:
            files = [path for path in folder.iterdir() if path.is_file()]
        except OSError:
            continue
        for path in files:
            suffix = path.suffix.lower()
            if suffix not in SUFFIXES:
                continue
            stats["files"] += 1
            stats["bytes"] += path.stat().st_size
            stats["by_suffix"][suffix] = stats["by_suffix"].get(suffix, 0) + 1
    return stats


def _allow_roots(roots) -> None:
    text = ", ".join(str(item) for item in roots)
    settings = config.USER.get("materials")
    materials = settings if isinstance(settings, dict) else {}
    dirs = list(materials.get("import_dirs") or [])
    for item in roots:
        if str(item) not in dirs:
            dirs.append(str(item))
    materials["import_dirs"] = dirs
    config.USER["materials"] = materials
    path = config.SETTINGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data["materials"] = materials
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已把导入白名单补上：{text}")


def _import(root: pathlib.Path) -> dict:
    total = {"imported": 0, "skipped": 0, "failed": 0, "scanned": 0, "dirs": 0}
    for folder in _dirs(root):
        try:
            files = [path for path in folder.iterdir() if path.is_file()]
        except OSError:
            continue
        if not any(path.suffix.lower() in SUFFIXES for path in files):
            continue
        try:
            result = materials_import.import_dir(
                str(folder), source="import", recursive=False)
        except Exception as exc:  # noqa: BLE001
            print(f"跳过 {folder}：{exc}")
            continue
        total["dirs"] += 1
        for key in ("imported", "skipped", "failed", "scanned"):
            total[key] += int(result.get(key) or 0)
        if result.get("imported"):
            print(f"{folder}：导入 {result['imported']} / 跳过 {result['skipped']}")
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roots", choices=("skill", "course", "all"), default="skill")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-roots", action="store_true")
    args = parser.parse_args()
    roots = []
    if args.roots in ("skill", "all"):
        roots.append(SKILL)
    if args.roots in ("course", "all"):
        roots.extend(COURSES)
    roots = [path for path in roots if path.exists()]
    if args.dry_run:
        for root in roots:
            print(root, json.dumps(_count(root), ensure_ascii=False))
        return 0
    if args.allow_roots:
        _allow_roots(roots)
    grand = {"imported": 0, "skipped": 0, "failed": 0, "scanned": 0, "dirs": 0}
    for root in roots:
        print(f"开始：{root}")
        result = _import(root)
        for key in grand:
            grand[key] += result[key]
        print(f"完成：{root} {result}")
    print(json.dumps(grand, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
