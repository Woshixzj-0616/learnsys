# -*- coding: utf-8 -*-
"""汇总检查所有校对 JSON：试卷是否存在、单元/句号是否对得上、补丁类型是否合法。

用法：
  D:\\cet6_tool\\.venv\\Scripts\\python.exe 汇总检查.py
  ... --corrections-dir D:\\cet6_tool\\校对 --papers D:\\Desktop\\六级精听\\试卷
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
DEFAULT_CORRECTIONS = Path(r"D:\cet6_tool\校对")
DEFAULT_PAPERS = Path(r"D:\Desktop\六级精听\试卷")


def load_paper(paper_dir: Path) -> dict:
    text = (paper_dir / "data.js").read_text(encoding="utf-8").strip()
    prefix = "window.PAPER ="
    if not text.startswith(prefix):
        raise ValueError("不是工作台 data.js")
    body = text[len(prefix):].strip()
    if body.endswith(";"):
        body = body[:-1]
    return json.loads(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总检查校对补丁")
    parser.add_argument("--corrections-dir", default=str(DEFAULT_CORRECTIONS))
    parser.add_argument("--papers", default=str(DEFAULT_PAPERS))
    args = parser.parse_args()

    corr_dir = Path(args.corrections_dir).expanduser().resolve()
    paper_root = Path(args.papers).expanduser().resolve()
    files = sorted(corr_dir.glob("*.json"))
    if not files:
        print(f"没有找到校对文件：{corr_dir}")
        return 1

    total_patches = 0
    problems = 0
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"✗ {path.name}：JSON 读取失败（{exc}）")
            problems += 1
            continue
        title = str(data.get("paper") or "").strip()
        items = data.get("items")
        if not title or not isinstance(items, dict):
            print(f"✗ {path.name}：缺少 paper 或 items")
            problems += 1
            continue
        paper_dir = paper_root / title
        if not paper_dir.is_dir():
            print(f"✗ {path.name}：找不到试卷目录「{title}」")
            problems += 1
            continue
        try:
            paper = load_paper(paper_dir)
        except Exception as exc:
            print(f"✗ {path.name}：data.js 读取失败（{exc}）")
            problems += 1
            continue
        units = {}
        for sec in paper.get("sections") or []:
            for item in sec.get("items") or []:
                units[item.get("title")] = {
                    int(s.get("i", -1)) for s in item.get("sentences") or []
                }
        n = 0
        bad = []
        for unit, patches in items.items():
            if unit not in units:
                bad.append(f"单元不存在「{unit}」")
                continue
            if not isinstance(patches, dict):
                bad.append(f"「{unit}」补丁不是对象")
                continue
            for key, patch in patches.items():
                try:
                    i = int(key)
                except (TypeError, ValueError):
                    bad.append(f"「{unit}」句号不是数字：{key}")
                    continue
                if i not in units[unit]:
                    bad.append(f"「{unit}」没有第 {i} 句")
                    continue
                if not isinstance(patch, (str, dict)):
                    bad.append(f"「{unit}」第 {i} 句补丁类型不对")
                    continue
                if isinstance(patch, dict) and not str(patch.get("en") or "").strip():
                    bad.append(f"「{unit}」第 {i} 句对象补丁缺少 en")
                    continue
                n += 1
        total_patches += n
        mark = "✓" if not bad else "✗"
        print(f"{mark} {title}：{n} 处，来源 {len(data.get('sources') or [])} 个")
        for msg in bad:
            print(f"    - {msg}")
            problems += 1

    print(f"\n汇总：{len(files)} 份校对文件，{total_patches} 处补丁，{problems} 个问题。")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
