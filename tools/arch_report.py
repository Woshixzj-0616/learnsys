"""体量门禁：单文件行数红线，防止模块拆分后又长回一个几千行的大文件。

红线只在这里定义一次；架构文档 `docs/架构-前后端.md` 只引用本脚本，不抄数字。

    .venv/Scripts/python.exe tools/arch_report.py            # 看报告
    .venv/Scripts/python.exe tools/arch_report.py --check    # 超线返回 1（测试用）
    .venv/Scripts/python.exe tools/arch_report.py --json     # 给脚本消费
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 红线：业务代码单文件行数。测试、构建产物、第三方依赖不算。
LIMITS = {".py": 500, ".js": 500, ".css": 600}
SCAN_ROOTS = ("learnsys", "web", "tools")
EXCLUDE_PARTS = {"tests", "build", "dist", ".venv", "models", "vendor",
                 "node_modules", "__pycache__", ".git"}
WATCH_LINES = 400      # 进入观察区：还没超线，但改功能前要想想是否该拆


def _line_count(path: pathlib.Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def scan(root: pathlib.Path | None = None) -> list[dict]:
    """扫描业务源码，按行数从大到小返回。"""
    root = pathlib.Path(root or ROOT)
    rows: list[dict] = []
    for name in SCAN_ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in LIMITS:
                continue
            rel = path.relative_to(root)
            if any(part in EXCLUDE_PARTS for part in rel.parts):
                continue
            lines = _line_count(path)
            limit = LIMITS[path.suffix]
            rows.append({
                "path": rel.as_posix(),
                "lines": lines,
                "limit": limit,
                "over": lines > limit,
                "watch": lines >= WATCH_LINES,
            })
    return sorted(rows, key=lambda row: (-row["lines"], row["path"]))


def violations(rows: list[dict] | None = None) -> list[dict]:
    return [row for row in (rows if rows is not None else scan()) if row["over"]]


def report(rows: list[dict] | None = None) -> str:
    rows = rows if rows is not None else scan()
    bad = [row for row in rows if row["over"]]
    watch = [row for row in rows if row["watch"] and not row["over"]]
    limits = "、".join(f"{suffix} ≤ {limit}" for suffix, limit in LIMITS.items())
    lines = [f"体量报告（红线：{limits} 行）", ""]
    if bad:
        lines.append(f"超线 {len(bad)} 个：")
        for row in bad:
            lines.append(f"  ✗ {row['path']}：{row['lines']} 行（上限 {row['limit']}）")
    else:
        lines.append("超线 0 个 —— 通过。")
    if watch:
        lines.append("")
        lines.append(f"观察区（≥{WATCH_LINES} 行，下次改到它时优先拆）：")
        for row in watch[:15]:
            lines.append(f"  · {row['path']}：{row['lines']} 行")
    lines.append("")
    lines.append("查看单个文件：`python tools/arch_report.py --json`")
    lines.append("索引：docs/架构-前后端.md")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学习工作台体量门禁")
    parser.add_argument("--check", action="store_true", help="超线返回非零（测试/CI 用）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    rows = scan()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(report(rows))
    if args.check and violations(rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
