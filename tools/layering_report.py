"""分层门禁：包级反向依赖必须为 0。

规则只在这里定义一次；`docs/架构-前后端.md` 只引用本脚本，不抄规则表。

    .venv/Scripts/python.exe tools/layering_report.py            # 看报告
    .venv/Scripts/python.exe tools/layering_report.py --check    # 有反向依赖返回 1
    .venv/Scripts/python.exe tools/layering_report.py --json     # 给脚本消费

方向约定（数字越小越底层）：
    core / store / browser  ← 不得依赖 services / agent / ask / server
    agent                   ← 不得依赖 ask / server
    services                ← 不得依赖 ask / server
    server                  ← 不得依赖 ask（HTTP 层不反向依赖桌面入口）

门禁零白名单：出现反向依赖就修依赖，不要把文件塞进豁免表。
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE_ROOT = ROOT / "learnsys"

# 包 → 禁止导入的包。只列「下层不得依赖上层」的反向边。
RULES: dict[str, tuple[str, ...]] = {
    "core": ("services", "agent", "ask", "server"),
    "store": ("services", "agent", "ask", "server"),
    "browser": ("services", "agent", "ask", "server"),
    "agent": ("ask", "server"),
    "services": ("ask", "server"),
    "server": ("ask",),
}


def _module_candidates(path: pathlib.Path) -> list[tuple[int, str]]:
    """文件里所有 import 的模块名（绝对形式），带行号。

    相对导入先还原成 `learnsys.xxx`；`from learnsys import ask` 这种
    名字本身是被导入的子模块，也一并算进去。
    """
    module_name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
    package_parts = module_name.split(".")[:-1]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package_parts) - node.level + 1
                base = package_parts[:max(keep, 0)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if target:
                found.append((node.lineno, target))
                for alias in node.names:
                    if alias.name != "*":
                        found.append((node.lineno, f"{target}.{alias.name}"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
    return found


def scan(root: pathlib.Path | None = None) -> list[dict]:
    """返回所有反向依赖；每条含文件、行号、所属包、被导入包。"""
    base = pathlib.Path(root or PACKAGE_ROOT)
    rows: list[dict] = []
    for package, banned in RULES.items():
        package_dir = base / package
        if not package_dir.is_dir():
            continue
        for path in sorted(package_dir.rglob("*.py")):
            seen: set[tuple[int, str]] = set()
            for lineno, module in _module_candidates(path):
                parts = module.split(".")
                if len(parts) < 2 or parts[0] != "learnsys":
                    continue
                top = parts[1]
                if top in banned and (lineno, top) not in seen:
                    seen.add((lineno, top))
                    rows.append({
                        "file": path.relative_to(ROOT).as_posix(),
                        "line": lineno,
                        "package": package,
                        "imported": top,
                        "module": module,
                    })
    return rows


def report(rows: list[dict] | None = None) -> str:
    rows = rows if rows is not None else scan()
    lines = ["分层报告（低层不得依赖高层：core/store/browser → services/agent/ask/server；"
             "agent/services → ask/server；server → ask）", ""]
    if not rows:
        lines.append("反向依赖 0 处 —— 通过。")
    else:
        lines.append(f"反向依赖 {len(rows)} 处：")
        for row in rows:
            lines.append(
                f"  ✗ {row['file']}:{row['line']}  {row['package']} → {row['imported']}"
                f"（{row['module']}）")
    lines.append("")
    lines.append("规则：`tools/layering_report.py` 的 RULES；索引：`docs/架构-前后端.md`")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学习工作台分层门禁")
    parser.add_argument("--check", action="store_true", help="有反向依赖时返回非零（测试/CI 用）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    rows = scan()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(report(rows))
    if args.check and rows:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
