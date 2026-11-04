"""构建并封存「对话总汇」。

    .venv/Scripts/python.exe tools/build_dialog_archive.py --dry-run
    .venv/Scripts/python.exe tools/build_dialog_archive.py
    .venv/Scripts/python.exe tools/build_dialog_archive.py --new-archive

默认只生成一份；已封存时再跑不会改文件。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store
from learnsys.services.dialog_archive.build import build_archive
from learnsys.services.dialog_archive.sources import SOURCES
from learnsys.store import memory_batches


def _inventory(cutoff_ts: float) -> list[dict]:
    rows = []
    for source in SOURCES:
        try:
            result = source.collect(cutoff_ts)
        except Exception as exc:  # noqa: BLE001
            rows.append({"id": source.id, "error": str(exc)})
            continue
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
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default=str(config.DATA_ROOT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--new-archive", action="store_true")
    parser.add_argument("--cutoff", default="",
                        help="ISO 时间；默认构建开始时")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.cutoff:
        cutoff_ts = dt.datetime.fromisoformat(args.cutoff).timestamp()
    else:
        cutoff_ts = time.time()

    if args.dry_run:
        rows = _inventory(cutoff_ts)
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        total = sum(row.get("chars", 0) for row in rows)
        print(f"预估正文 {total / 1024 / 1024:.1f} MB")
        return 0

    result = build_archive(args.data_root, cutoff_ts=cutoff_ts,
                           new_archive=args.new_archive)
    db_path = pathlib.Path(args.data_root) / "learning.db"
    if not result.get("already_sealed"):
        try:
            conn = store.connect(db_path)
            try:
                batch = memory_batches.create_batch(
                    conn, "dialog_archive", status="sealed",
                    archive_id=result.get("archive_id", ""),
                    archive_path=result.get("path", ""),
                    cutoff_at=dt.datetime.fromtimestamp(cutoff_ts).strftime(
                        "%Y-%m-%dT%H:%M:%S"),
                    body_sha256=result.get("body_sha256", ""),
                    file_sha256=result.get("file_sha256", ""),
                    stats_json={"sources": result.get("sources", [])},
                    missing_json=result.get("missing", []),
                    finished_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                result["batch_id"] = batch
            finally:
                conn.close()
        except Exception as exc:  # 批次记账失败不影响档案本身
            result["batch_error"] = str(exc)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result.get("already_sealed"):
            print(f"已封存，未改动：{result['path']}")
        else:
            print(f"完成：{result['path']}")
            print(f"会话 {result['sessions']} / 消息 {result['messages']} / "
                  f"正文 {result['body_bytes'] / 1024 / 1024:.1f} MB")
            print(f"正文哈希 {result['body_sha256'][:16]}…")
            if result.get("missing"):
                print("缺失来源：" + "；".join(result["missing"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
