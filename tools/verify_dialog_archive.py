"""校验封存的对话总汇：正文哈希、末尾哨兵、锚点数量。"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys.services.dialog_archive.build import verify_archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify_archive(args.path)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result.get("ok"):
            print(f"通过：{args.path}")
            print(f"消息 {result.get('message_count')} 条 / "
                  f"{result.get('size', 0) / 1024 / 1024:.1f} MB")
        else:
            print(f"失败：{result.get('reason')}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
