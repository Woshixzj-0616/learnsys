# -*- coding: utf-8 -*-
"""把 `校对/<试卷标题>.json` 应用到已有试卷的 data.js / 时间轴.json。

用法：
  python apply_corrections.py --title "英语六级强化刷题卷三"
  python apply_corrections.py --dir "D:\\Desktop\\六级精听\\试卷\\英语六级强化刷题卷三"
  python apply_corrections.py --title "卷三" --no-audio   # 只改文本，不重切 MP3

默认试卷根目录是 `D:\\Desktop\\六级精听\\试卷`，可用 --papers 覆盖。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from transcript_fixes import (
    apply_to_paper,
    load_corrections,
    recut_changed_sentences,
)

DEFAULT_PAPERS = Path(r"D:\Desktop\六级精听\试卷")
DATA_PREFIX = "window.PAPER ="


def read_data_js(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped.startswith(DATA_PREFIX):
        raise ValueError(f"不是工作台的 data.js：{path}")
    body = stripped[len(DATA_PREFIX):].strip()
    if body.endswith(";"):
        body = body[:-1]
    return json.loads(body)


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_outputs(paper_dir: Path, paper: dict) -> None:
    body = json.dumps(paper, ensure_ascii=False, indent=2)
    write_atomic(paper_dir / "data.js", DATA_PREFIX + " " + body + ";\n")
    write_atomic(paper_dir / "时间轴.json", body + "\n")


def pick_dir(args) -> Path:
    if args.dir:
        return Path(args.dir).expanduser().resolve()
    root = Path(args.papers).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"找不到试卷根目录：{root}")
    exact = root / args.title
    if exact.is_dir():
        return exact
    hits = [p for p in root.iterdir() if p.is_dir() and args.title in p.name]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"找不到标题包含「{args.title}」的试卷目录：{root}")
    names = "、".join(p.name for p in hits[:8])
    raise SystemExit(f"「{args.title}」匹配到多份试卷，请写完整标题：{names}")


def main() -> int:
    parser = argparse.ArgumentParser(description="应用人工校对过的听力原文")
    parser.add_argument("--title", default="", help="试卷标题（或标题片段）")
    parser.add_argument("--dir", default="", help="直接指定试卷目录")
    parser.add_argument("--papers", default=str(DEFAULT_PAPERS), help="试卷根目录")
    parser.add_argument("--no-audio", action="store_true", help="只改文本，不重切逐句 MP3")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    args = parser.parse_args()
    if not args.dir and not args.title:
        parser.error("需要 --title 或 --dir")

    paper_dir = pick_dir(args)
    data_js = paper_dir / "data.js"
    if not data_js.is_file():
        raise SystemExit(f"找不到 data.js：{data_js}")

    paper = read_data_js(data_js)
    title = str(paper.get("title") or paper_dir.name)
    corrections = load_corrections(title)
    if not corrections:
        raise SystemExit(f"没有校对文件：{title}（校对目录 D:\\cet6_tool\\校对）")

    old_fix = json.dumps(paper.get("transcript_fixes"), ensure_ascii=False, sort_keys=True)
    changes = apply_to_paper(paper, corrections)
    new_fix = json.dumps(paper.get("transcript_fixes"), ensure_ascii=False, sort_keys=True)
    if not changes and old_fix == new_fix:
        print(f"没有可应用的改动：{title}")
        return 0
    if not changes:
        print(f"文本没有变化，只更新校对元数据：{title}")

    print(f"试卷：{title}")
    print(f"目录：{paper_dir}")
    print(f"校对来源：{corrections.get('checked_at', '')}")
    for c in changes:
        extra = []
        if c.get("start_changed"):
            extra.append("起点")
        if c.get("end_changed"):
            extra.append("终点")
        suffix = "（" + "、".join(extra) + "）" if extra else ""
        print(f"  {c['section']} / {c['item']} 第 {c['i']} 句{suffix}")
        print(f"    旧：{c['old']}")
        print(f"    新：{c['new']}")

    if args.dry_run:
        print(f"\n预演：共 {len(changes)} 处，未写文件。")
        return 0

    write_outputs(paper_dir, paper)

    recut = 0
    if not args.no_audio:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
        if ffmpeg:
            recut = recut_changed_sentences(paper_dir, paper, changes, ffmpeg)
        else:
            print("提示：没有找到 ffmpeg，逐句 MP3 未重切。")
    print(f"\n完成：写入 {len(changes)} 处校对"
          + (f"，重切 {recut} 个逐句 MP3" if recut else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
