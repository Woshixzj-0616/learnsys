"""把个人资料和封存对话抽成长期记忆。

    .venv/Scripts/python.exe tools/extract_memories.py --profiles
    .venv/Scripts/python.exe tools/extract_memories.py --all --dry-run
    .venv/Scripts/python.exe tools/extract_memories.py --all --max-calls 30
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store
from learnsys.services.dialog_archive import (
    extract,
    profile_import,
)
from learnsys.store import memory_batches


def _latest_archive(data_root) -> pathlib.Path | None:
    folder = pathlib.Path(data_root) / "记忆档案"
    files = sorted(folder.glob("对话总汇-*.md"))
    return files[-1] if files else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default=str(config.DATA_ROOT))
    parser.add_argument("--archive", default="")
    parser.add_argument("--profiles", action="store_true")
    parser.add_argument("--diaries", action="store_true")
    parser.add_argument("--ideas", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--extract", action="store_true",
                        help="从封存对话总汇抽事实（会调模型）")
    parser.add_argument("--strict", action="store_true",
                        help="只抽用户亲口说出长期偏好的块")
    parser.add_argument("--exclude-projects", action="store_true",
                        help="排除旅行/金融/项目类话题")
    parser.add_argument("--candidate-only", action="store_true",
                        help="抽出的全部进候选，不自动 active")
    parser.add_argument("--max-calls", type=int, default=150)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    do_all = args.all or not (
        args.profiles or args.diaries or args.ideas or args.extract)
    results: dict = {}
    conn = store.connect(pathlib.Path(args.data_root) / "learning.db")
    try:
        if do_all or args.profiles:
            results["profiles"] = profile_import.import_profiles(
                conn, dry_run=args.dry_run)
        if do_all or args.diaries:
            results["diaries"] = profile_import.import_diaries(
                conn, dry_run=args.dry_run)
        if do_all or args.ideas:
            results["ideas"] = profile_import.import_ideas(
                conn, dry_run=args.dry_run)
        archive = pathlib.Path(args.archive) if args.archive else _latest_archive(
            args.data_root)
        run_archive = bool(args.all or args.extract or args.archive)
        if run_archive and archive and archive.exists():
            batch_id = 0
            if not args.dry_run:
                batch_id = memory_batches.create_batch(
                    conn, "fact_extract", archive_path=str(archive),
                    archive_id=archive.stem)
            results["archive"] = extract.extract_archive(
                conn, archive, batch_id=batch_id, max_calls=args.max_calls,
                dry_run=args.dry_run, data_root=args.data_root,
                strict=args.strict, exclude_projects=args.exclude_projects,
                candidate_only=args.candidate_only)
            if batch_id:
                memory_batches.update_batch(
                    conn, batch_id, status="done",
                    stats_json=results["archive"],
                    finished_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        elif run_archive:
            results["archive"] = {"ok": False, "reason": "没有找到对话总汇"}
    finally:
        conn.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
