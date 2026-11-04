"""只读盘点各对话来源：文件、会话、消息、正文字符、坏行与缺失。"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys.services.dialog_archive.sources import SOURCES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = []
    for source in SOURCES:
        try:
            result = source.collect(time.time())
            sessions = result.get("sessions") or []
            rows.append({
                "id": source.id,
                "files": result.get("files") or 0,
                "sessions": len(sessions),
                "messages": sum(len(item.messages) for item in sessions),
                "chars": sum(len(m.text) for item in sessions for m in item.messages),
                "skipped": result.get("skipped") or 0,
                "errors": result.get("errors") or 0,
                "missing": result.get("missing") or source.missing_reason,
            })
        except Exception as exc:  # noqa: BLE001
            rows.append({"id": source.id, "files": 0, "sessions": 0,
                         "messages": 0, "chars": 0, "skipped": 0,
                         "errors": 1, "missing": f"收集失败：{exc}"})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{row['id']:<12} 文件{row.get('files', 0):>4} "
                  f"会话{row.get('sessions', 0):>4} 消息{row.get('messages', 0):>6} "
                  f"字符{row.get('chars', 0):>9} 跳过{row.get('skipped', 0):>5} "
                  f"错误{row.get('errors', 0):>3} {row.get('missing', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
