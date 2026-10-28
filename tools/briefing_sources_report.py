"""每日简报信息源探活：每个源是否可达、解析到几条、最新一条是什么时候。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools\\briefing_sources_report.py
    ... --json
    ... --timeout 12 --strict

只读网络，不写数据库。源失效时先跑它，再决定替换哪个源。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys.services.briefing import feed
from learnsys.services.briefing.sources import SOURCES


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="每日简报信息源探活")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--timeout", type=float, default=10.0, help="单源超时秒数")
    parser.add_argument("--strict", action="store_true", help="有源失败时退出码为 1")
    args = parser.parse_args()

    items, stats = feed.fetch_all(timeout=args.timeout)
    ok = sum(1 for value in stats.values() if value.get("status") == "ok")
    if args.json:
        print(json.dumps({"ok": ok, "total": len(stats), "items": len(items),
                          "sources": stats}, ensure_ascii=False, indent=2))
    else:
        print(f"源 {len(stats)} 个 · 可用 {ok} · 条目 {len(items)}")
        for source in SOURCES:
            stat = stats.get(source.id) or {}
            status = "可用" if stat.get("status") == "ok" else "失败"
            line = (f"  {status}  {source.name:<18} "
                    f"{stat.get('count', 0):>3} 条 · 最新 {stat.get('latest') or '—'}")
            print(line)
            if stat.get("error"):
                print(f"         {stat['error']}")
    return 1 if args.strict and ok < len(stats) else 0


if __name__ == "__main__":
    raise SystemExit(main())
