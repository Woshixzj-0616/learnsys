"""把 v1 的按天库（D:/学习系统/2026.10.2/learnsys.db）迁进 v2 统一库。

只读源库，不删不改；重复跑会跳过已经迁过的源（migrated_sources 里记着）。
迁移前请先备份 D:/学习系统。

用法：
  .venv\\Scripts\\python.exe tools\\migrate_v1_to_v2.py
  .venv\\Scripts\\python.exe tools\\migrate_v1_to_v2.py --data-root D:/学习系统 --verbose
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config                       # noqa: E402
from learnsys.core import db as core_db            # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="v1 按天库 → v2 统一库")
    parser.add_argument("--data-root", default=str(config.DATA_ROOT))
    parser.add_argument("--target", default="", help="默认 <data-root>/learning.db")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    data_root = pathlib.Path(args.data_root)
    target = pathlib.Path(args.target) if args.target else data_root / "learning.db"
    sources = core_db._day_dbs(data_root)
    print(f"数据根：{data_root}")
    print(f"目标库：{target}")
    print(f"找到 {len(sources)} 个 v1 按天库：")
    for day, path in sources:
        print(f"  - {day.isoformat()}  {path}")
    if not sources:
        print("没有可迁移的按天库。")
        return 0

    report = core_db.migrate_from_v1(data_root, target, verbose=args.verbose)
    print("")
    print(f"本次迁移 {len(report['sources'])} 个库，跳过 {len(report['skipped'])} 个已迁库。")
    for item in report["sources"]:
        counts = item["counts"]
        print(f"  ✓ {item['path']}")
        print(f"    会话 {counts['sessions']} · 窗口 {counts['window_events']} · "
              f"转写 {counts['transcripts']} · 问答 {counts['asks']} · 快照文字 {counts['frame_text']}")
    print("")
    print("统一库现有：")
    for key, value in report["counts"].items():
        print(f"  {key}: {value}")
    print("")
    print("完成。源库未改动；v2 以后只读写 learning.db。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
