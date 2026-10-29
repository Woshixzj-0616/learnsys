"""分层门禁：包级反向依赖必须为 0，路由层不得直接写 SQL。

规则只在这里定义一次；`docs/架构-前后端.md` 只引用本脚本，不抄规则表。

    .venv/Scripts/python.exe tools/layering_report.py            # 看报告
    .venv/Scripts/python.exe tools/layering_report.py --check    # 有违规返回 1
    .venv/Scripts/python.exe tools/layering_report.py --json     # 给脚本消费

方向约定（数字越小越底层）：
    core / store / browser / llm  ← 不得依赖 services / agent / ask / server
    agent                         ← 不得依赖 ask / server
    services                      ← 不得依赖 ask / server
    server                        ← 不得依赖 ask（HTTP 层不反向依赖桌面入口）

路由层（`server/routes_*`）只做参数校验、鉴权、拼响应；SQL 归 store。
门禁零白名单：出现反向依赖就修依赖，不要把文件塞进豁免表。
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE_ROOT = ROOT / "learnsys"

# 包 → 禁止导入的包。只列「下层不得依赖上层」的反向边。
RULES: dict[str, tuple[str, ...]] = {
    "core": ("services", "agent", "ask", "server"),
    "store": ("services", "agent", "ask", "server"),
    "browser": ("services", "agent", "ask", "server"),
    "llm": ("store", "services", "agent", "ask", "server"),
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


# 路由层只认这些大写 SQL 关键字 —— 和小写英文单词区分开，减少误报。
_SQL_WORDS = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b")


def scan_route_sql(root: pathlib.Path | None = None) -> list[dict]:
    """路由文件里直接出现的 SQL；每条含文件、行号、源码行。"""
    server = pathlib.Path(root or PACKAGE_ROOT) / "server"
    rows: list[dict] = []
    for path in sorted(server.rglob("*.py")):
        parts = path.relative_to(server).parts
        if not (path.name.startswith("routes_") or parts[0].startswith("routes_")):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _SQL_WORDS.search(line):
                rows.append({"file": path.relative_to(ROOT).as_posix(),
                             "line": lineno, "text": stripped[:120]})
    return rows


def package_edges(root: pathlib.Path | None = None) -> dict[str, set[str]]:
    """包级导入图：`{包: {它导入的其他包}}`。"""
    base = pathlib.Path(root or PACKAGE_ROOT)
    packages = {path.name for path in base.iterdir()
                if path.is_dir() and (path / "__init__.py").exists()
                and path.name != "__pycache__"}
    graph: dict[str, set[str]] = {name: set() for name in packages}
    for package in packages:
        for path in (base / package).rglob("*.py"):
            for _, module in _module_candidates(path):
                parts = module.split(".")
                if (len(parts) >= 2 and parts[0] == "learnsys"
                        and parts[1] in packages and parts[1] != package):
                    graph[package].add(parts[1])
    return graph


def cycles(graph: dict[str, set[str]] | None = None) -> list[list[str]]:
    """包级循环依赖；每条环只报一次（按包集合去重）。"""
    graph = graph if graph is not None else package_edges()
    found: list[list[str]] = []
    seen: set[frozenset[str]] = set()
    done: set[str] = set()
    stack: list[str] = []
    position: dict[str, int] = {}

    def visit(node: str) -> None:
        position[node] = len(stack)
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            if nxt in position:
                loop = stack[position[nxt]:] + [nxt]
                key = frozenset(loop)
                if key not in seen:
                    seen.add(key)
                    found.append(loop)
            elif nxt not in done:
                visit(nxt)
        stack.pop()
        position.pop(node, None)
        done.add(node)

    for node in sorted(graph):
        if node not in done:
            visit(node)
    return found


def report(rows: list[dict] | None = None,
           loops: list[list[str]] | None = None,
           route_sql: list[dict] | None = None) -> str:
    rows = rows if rows is not None else scan()
    loops = loops if loops is not None else cycles()
    route_sql = route_sql if route_sql is not None else scan_route_sql()
    lines = ["分层报告（低层不得依赖高层：core/store/browser → services/agent/ask/server；"
             "llm → store/services/agent/ask/server；agent/services → ask/server；server → ask）", ""]
    if not rows:
        lines.append("反向依赖 0 处 —— 通过。")
    else:
        lines.append(f"反向依赖 {len(rows)} 处：")
        for row in rows:
            lines.append(
                f"  ✗ {row['file']}:{row['line']}  {row['package']} → {row['imported']}"
                f"（{row['module']}）")
    if route_sql:
        lines.append(f"路由层直接写 SQL {len(route_sql)} 处（SQL 归 store）：")
        for row in route_sql:
            lines.append(f"  ✗ {row['file']}:{row['line']}  {row['text']}")
    else:
        lines.append("路由层直接写 SQL 0 处 —— 通过。")
    if loops:
        # 同级复用的循环（如 services 调用 agent.run）由规则允许，不计入失败；
        # 这里只报告，方便评审时看见全图，不用它卡 CI。
        lines.append(f"包级循环依赖 {len(loops)} 个（同级复用，不计入失败）：")
        for loop in loops:
            lines.append("  · " + " → ".join(loop))
    lines.append("")
    lines.append("规则：`tools/layering_report.py` 的 RULES；索引：`docs/架构-前后端.md`")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学习工作台分层门禁")
    parser.add_argument("--check", action="store_true", help="有反向依赖时返回非零（测试/CI 用）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    rows = scan()
    loops = cycles()
    route_sql = scan_route_sql()
    if args.json:
        print(json.dumps({"violations": rows, "cycles": loops,
                          "route_sql": route_sql},
                         ensure_ascii=False, indent=1))
    else:
        print(report(rows, loops, route_sql))
    if args.check and (rows or route_sql):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
