# -*- coding: utf-8 -*-
"""抓懒笔记某一套听力的 7 篇英文原文，按单元存成纯文本，供对齐检查。

用法：
  D:\\cet6_tool\\.venv\\Scripts\\python.exe 抓懒笔记.py --slug 2016-06-1
输出：
  D:\\cet6_tool\\校对工具\\_tmp\\2016-06-1\\Conversation 1.txt ...
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = "https://english-exam.lazynote.cn/cet6/articles/{slug}/{part}/"
PARTS = [
    ("Conversation 1", "part2-section-a-1"),
    ("Conversation 2", "part2-section-a-2"),
    ("Passage 1", "part2-section-b-1"),
    ("Passage 2", "part2-section-b-2"),
    ("Recording 1", "part2-section-c-1"),
    ("Recording 2", "part2-section-c-2"),
    ("Recording 3", "part2-section-c-3"),
]
OUT = Path(__file__).resolve().parent / "_tmp"
SPEAKER_RE = re.compile(r"^\s*(?:M|W|Man|Woman|Interviewer|Speaker)\s*[:：]\s*", re.I)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def paragraphs(page: str) -> list[str]:
    blocks = re.findall(r'<div class="art-passage__para"[^>]*>(.*?)</div>', page, re.S)
    out = []
    for block in blocks:
        match = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        if not match:
            continue
        text = re.sub(r"<[^>]+>", "", match.group(1))
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        text = SPEAKER_RE.sub("", text)
        if text:
            out.append(text)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="抓懒笔记听力原文")
    parser.add_argument("--slug", required=True, help="如 2016-06-1")
    parser.add_argument("--out", default=str(OUT), help="输出目录")
    args = parser.parse_args()
    out_dir = Path(args.out) / args.slug
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for unit, part in PARTS:
        url = BASE.format(slug=args.slug, part=part)
        try:
            page = fetch(url)
        except Exception as exc:
            print(f"✗ {unit}：{exc}")
            continue
        lines = paragraphs(page)
        path = out_dir / (unit + ".txt")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        total += len(lines)
        print(f"✓ {unit}：{len(lines)} 段 -> {path}")
    print(f"\n共 {total} 段。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
