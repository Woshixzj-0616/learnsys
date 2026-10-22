# -*- coding: utf-8 -*-
"""把一段线上原文（纯文本文件）和 data.js 里的某段做词级对齐，打印差异。

用法：
  D:\\cet6_tool\\.venv\\Scripts\\python.exe 对齐检查.py --title "试卷标题" --unit "Conversation 1" --text-file c1.txt

text-file 每行一句即可；题目行（Questions / Question N:）会被自动去掉。
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
DEFAULT_PAPERS = Path(r"D:\Desktop\六级精听\试卷")


def pick_dir(args) -> Path:
    if args.dir:
        return Path(args.dir).expanduser().resolve()
    root = Path(args.papers).expanduser().resolve()
    exact = root / args.title
    if exact.is_dir():
        return exact
    hits = [p for p in root.iterdir() if p.is_dir() and args.title in p.name]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"找不到试卷：{args.title}（{root}）")
    names = "、".join(p.name for p in hits[:8])
    raise SystemExit(f"标题匹配到多份试卷，请写完整：{names}")


def load_paper(paper_dir: Path) -> dict:
    path = paper_dir / "data.js"
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.PAPER ="
    if not text.startswith(prefix):
        raise SystemExit(f"不是工作台 data.js：{path}")
    body = text[len(prefix):].strip()
    if body.endswith(";"):
        body = body[:-1]
    return json.loads(body)


def norm(text: str) -> str:
    text = text.lower().replace("—", " ").replace("--", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9%$' ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_online(lines: list[str]) -> list[str]:
    out = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Questions ") or re.match(r"Question \d+:", line):
            break
        if line.startswith("All Rights"):
            continue
        out.append(line)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="线上原文与 data.js 的词级差异")
    parser.add_argument("--title", default="", help="试卷标题或标题片段")
    parser.add_argument("--dir", default="", help="直接指定试卷目录")
    parser.add_argument("--papers", default=str(DEFAULT_PAPERS), help="试卷根目录")
    parser.add_argument("--unit", required=True, help="题型单元，如 Conversation 1")
    parser.add_argument("--text-file", required=True, help="线上英文原文（每行一句）")
    parser.add_argument("--show-sentences", action="store_true", help="同时打印本段每句")
    args = parser.parse_args()
    if not args.dir and not args.title:
        parser.error("需要 --title 或 --dir")

    paper_dir = pick_dir(args)
    paper = load_paper(paper_dir)
    item = None
    for sec in paper.get("sections") or []:
        for cur in sec.get("items") or []:
            if cur.get("title") == args.unit:
                item = cur
                break
        if item:
            break
    if item is None:
        titles = [c.get("title") for s in paper.get("sections") or [] for c in s.get("items") or []]
        raise SystemExit(f"找不到题型单元「{args.unit}」。可选：{titles}")

    online = clean_online(Path(args.text_file).read_text(encoding="utf-8").splitlines())
    ours = [str(s.get("en") or "") for s in item.get("sentences") or []]
    a = norm(" ".join(ours)).split()
    b = norm(" ".join(online)).split()
    print(f"试卷：{paper.get('title') or paper_dir.name}")
    print(f"单元：{item.get('title')}（我们 {len(ours)} 句 / 线上 {len(online)} 行）")
    if args.show_sentences:
        print("\n--- 我们的句子 ---")
        for s in item.get("sentences") or []:
            print(f"{s.get('i')}\t{s.get('start')}\t{s.get('end')}\t{s.get('en')}")

    print("\n--- 词级差异 ---")
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    n = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        n += 1
        print(f"{tag}: 我们[{' '.join(a[i1:i2])}] -> 线上[{' '.join(b[j1:j2])}]")
    if not n:
        print("没有词级差异。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
