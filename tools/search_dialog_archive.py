"""检索封存的对话总汇。

    .venv/Scripts/python.exe tools/search_dialog_archive.py "六级 精听"
    .venv/Scripts/python.exe tools/search_dialog_archive.py "双指针" --limit 5 --json
    .venv/Scripts/python.exe tools/search_dialog_archive.py --read "archive:.../m0003"
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config
from learnsys.services.dialog_archive import search


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="", help="关键词，多个词用空格分开")
    parser.add_argument("--path", default="", help="档案路径；默认取最新一份")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--read", default="", help="按锚点读完整消息")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    path = pathlib.Path(args.path) if args.path else search.latest_archive(
        config.DATA_ROOT)
    if path is None or not path.exists():
        print("没有找到封存的对话总汇。")
        return 1
    if args.read:
        item = search.read_message(path, args.read)
        if item is None:
            print("没有找到这个锚点。")
            return 1
        if args.json:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        else:
            print(f"{item['at']} · {item['role']} · {item['anchor']}\n")
            print(item["text"])
        return 0
    hits = search.search_archive(path, args.query, limit=args.limit)
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print(f"没有找到「{args.query}」。")
        return 0
    for index, item in enumerate(hits, 1):
        print(f"[{index}] {item['at'][:10]} · {item['source']} · "
              f"{item['role']}\n    {item['snippet']}\n    {item['anchor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
