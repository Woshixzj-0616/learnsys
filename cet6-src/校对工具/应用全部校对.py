# -*- coding: utf-8 -*-
"""批量应用 `校对/*.json` 到各试卷的 data.js / 时间轴.json。

默认预演；加 --apply 才真正写文件和重切逐句 MP3。
  D:\\cet6_tool\\.venv\\Scripts\\python.exe 应用全部校对.py
  ... --apply
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
TOOL = Path(__file__).resolve().parent.parent
CORR = TOOL / "校对"
APPLY = TOOL / "apply_corrections.py"
PYTHON = TOOL / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    parser = argparse.ArgumentParser(description="批量应用校对补丁")
    parser.add_argument("--apply", action="store_true", help="真正写入；不加只预演")
    parser.add_argument("--no-audio", action="store_true", help="不重切逐句 MP3")
    args = parser.parse_args()

    files = sorted(CORR.glob("*.json"))
    if not files:
        print(f"没有校对文件：{CORR}")
        return 1

    ok = 0
    failed = 0
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"✗ {path.name}：{exc}")
            failed += 1
            continue
        title = str(data.get("paper") or "").strip()
        if not title:
            print(f"✗ {path.name}：缺少 paper")
            failed += 1
            continue
        cmd = [str(PYTHON), str(APPLY), "--title", title]
        if not args.apply:
            cmd.append("--dry-run")
        if args.no_audio:
            cmd.append("--no-audio")
        print(f"\n=== {title} ===")
        result = subprocess.run(cmd, cwd=str(TOOL))
        if result.returncode == 0:
            ok += 1
        else:
            failed += 1

    print(f"\n完成：{ok} 份成功，{failed} 份失败。")
    if not args.apply:
        print("这是预演；确认后加 --apply 真正写入。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
