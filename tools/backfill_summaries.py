"""回填旧会话摘要 / 记忆（显式运行，不自动执行）。

    .venv\\Scripts\\python.exe -X utf8 tools\\backfill_summaries.py --dry-run
    .venv\\Scripts\\python.exe -X utf8 tools\\backfill_summaries.py --limit 10
    .venv\\Scripts\\python.exe -X utf8 tools\\backfill_summaries.py --all   # 连已有摘要也重做

默认只处理「消息 >= 4 条且还没有摘要」的会话；每个会话一次快模型调用（会计入账本）。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store                      # noqa: E402
from learnsys.agent import post_turn                      # noqa: E402


def _candidates(conn, *, all_items: bool, limit: int) -> list[tuple[int, int, str]]:
    rows = conn.execute(
        "SELECT c.id, COUNT(m.id), COALESCE(c.summary, '') "
        "FROM conversations c JOIN messages m ON m.conversation_id = c.id "
        "GROUP BY c.id HAVING COUNT(m.id) >= ? ORDER BY c.updated_at DESC",
        (post_turn.EVERY_MESSAGES,)).fetchall()
    picked = []
    for conv_id, count, summary in rows:
        if not all_items and str(summary or "").strip():
            continue
        picked.append((int(conv_id), int(count), str(summary or "")))
        if limit and len(picked) >= limit:
            break
    return picked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回填会话摘要与长期记忆")
    parser.add_argument("--db", default=str(config.db_path()), help="数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="只列出要处理的会话")
    parser.add_argument("--limit", type=int, default=0, help="最多处理几个（0=不限）")
    parser.add_argument("--all", action="store_true", help="已有摘要也重做")
    args = parser.parse_args(argv)

    conn = store.connect(pathlib.Path(args.db))
    try:
        picked = _candidates(conn, all_items=args.all, limit=max(0, args.limit))
    finally:
        conn.close()
    if not picked:
        print("没有需要回填的会话。")
        return 0
    print(f"待处理 {len(picked)} 个会话（每个一次模型调用）：")
    for conv_id, count, summary in picked[:20]:
        state = "已有摘要，重做" if str(summary).strip() else "无摘要"
        print(f"  · #{conv_id}  {count} 条消息  {state}")
    if len(picked) > 20:
        print(f"  …还有 {len(picked) - 20} 个")
    if args.dry_run:
        print("这是预演，没有调用模型。去掉 --dry-run 才会执行。")
        return 0

    done = 0
    memories = 0
    for conv_id, _count, _summary in picked:
        try:
            result = post_turn.run_once(conv_id, config.DATA_ROOT)
        except Exception as exc:              # noqa: BLE001 —— 单个失败不挡后面
            print(f"  · #{conv_id} 失败：{exc}")
            continue
        done += 1
        memories += int(result.get("memories") or 0)
        text = str(result.get("summary") or "")
        print(f"  · #{conv_id} 完成：{text[:40] or '（空摘要）'}  新记忆 {result.get('memories', 0)}")
    print(f"完成 {done} 个会话，新增长期记忆 {memories} 条。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
