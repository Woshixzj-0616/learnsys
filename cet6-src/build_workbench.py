# -*- coding: utf-8 -*-
"""把 workbench_src 下的分层源码构建成单文件工作台。

用法：
  python build_workbench.py
  python build_workbench.py --check
  python build_workbench.py --out D:\\cet6_tool\\workbench_template.next.html
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
SRC_DIR = TOOL_DIR / "workbench_src"
SHELL = SRC_DIR / "shell.html"
STYLE_DIR = SRC_DIR / "styles"
JS_DIR = SRC_DIR / "js"
DEFAULT_OUT = TOOL_DIR / "workbench_template.html"
BUILD_VERSION = "2"
BUILD_RE = re.compile(r"<!-- WB-BUILD hash=([0-9a-f]{16}) built=(.+?) -->")
REQUIRES_RE = re.compile(r"^//\s*@requires:\s*(.+)$", re.M)
IMPORT_RE = re.compile(r"^\s*(?:import|export)\s", re.M)


class BuildError(Exception):
    pass


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildError(f"读取失败：{path}（{exc}）") from exc


def collect_files() -> tuple[list[Path], list[Path]]:
    styles = sorted(STYLE_DIR.glob("*.css"), key=lambda p: p.name)
    scripts = sorted(JS_DIR.glob("*.js"), key=lambda p: p.name)
    if not styles:
        raise BuildError(f"没有找到 CSS：{STYLE_DIR}")
    if not scripts:
        raise BuildError(f"没有找到 JS：{JS_DIR}")
    return styles, scripts


def validate_requires(scripts: list[Path]) -> None:
    seen: set[str] = set()
    for path in scripts:
        text = read_text(path)
        match = REQUIRES_RE.search(text)
        if not match:
            raise BuildError(f"{path.name} 缺少 // @requires: 声明")
        raw = match.group(1).strip()
        deps = [] if raw.lower() == "none" else [
            item.strip() for item in raw.split(",") if item.strip()
        ]
        for dep in deps:
            if dep not in seen:
                raise BuildError(
                    f"{path.name} 依赖 {dep}，但该文件没有排在它前面（检查文件名前缀）"
                )
        if path.name in seen:
            raise BuildError(f"文件名重复或顺序异常：{path.name}")
        seen.add(path.name)


def validate_scripts(scripts: list[Path]) -> None:
    for path in scripts:
        text = read_text(path)
        if "</script" in text.lower():
            raise BuildError(f"{path.name} 含有 </script>，会破坏内联脚本")
        if IMPORT_RE.search(text):
            raise BuildError(f"{path.name} 使用了 import/export；file:// 下不能用 ES module")


def build_html() -> tuple[str, str, int, int]:
    styles, scripts = collect_files()
    validate_requires(scripts)
    validate_scripts(scripts)

    shell = read_text(SHELL)
    if shell.count("{{WB_CSS}}") != 1 or shell.count("{{WB_JS}}") != 1:
        raise BuildError("shell.html 必须各有一个 {{WB_CSS}} 和 {{WB_JS}} 占位符")

    css_parts = []
    for path in styles:
        body = read_text(path)
        if "{{" in body:
            raise BuildError(f"{path.name} 含有未处理的占位符")
        css_parts.append(f"/* ---- {path.name} ---- */\n{body}")
    css_text = "\n\n".join(css_parts)

    js_parts = []
    for path in scripts:
        body = read_text(path)
        if "{{" in body:
            raise BuildError(f"{path.name} 含有未处理的占位符")
        js_parts.append(
            "<script>\n"
            f"// ---- {path.name} ----\n"
            f"{body}\n"
            "</script>"
        )
    js_text = "\n".join(js_parts)

    digest = hashlib.sha256()
    digest.update(BUILD_VERSION.encode("utf-8"))
    digest.update(shell.encode("utf-8"))
    for path in styles:
        digest.update(path.name.encode("utf-8"))
        digest.update(read_text(path).encode("utf-8"))
    for path in scripts:
        digest.update(path.name.encode("utf-8"))
        digest.update(read_text(path).encode("utf-8"))
    short_hash = digest.hexdigest()[:16]

    html = shell.replace("{{WB_CSS}}", css_text).replace("{{WB_JS}}", js_text)
    if "{{" in html:
        raise BuildError("构建结果里仍有未替换的占位符")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    banner = f"<!-- WB-BUILD hash={short_hash} built={stamp} -->\n"
    html = html.replace("<!DOCTYPE html>", "<!DOCTYPE html>\n" + banner, 1)
    return html, short_hash, len(styles), len(scripts)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def current_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    head = path.read_text(encoding="utf-8", errors="replace")[:200]
    match = BUILD_RE.search(head)
    return match.group(1) if match else None


def ensure_built() -> Path | None:
    """供 split_listening.install_workbench 调用：源码存在时按需重建产物。"""
    if not SRC_DIR.exists():
        return DEFAULT_OUT if DEFAULT_OUT.exists() else None
    html, short_hash, _, _ = build_html()
    if current_hash(DEFAULT_OUT) != short_hash:
        write_atomic(DEFAULT_OUT, html)
        print(f"工作台已重新构建：{DEFAULT_OUT}")
    return DEFAULT_OUT


def main() -> int:
    parser = argparse.ArgumentParser(description="构建单文件精听工作台")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出 HTML 路径")
    parser.add_argument("--check", action="store_true", help="只检查产物是否最新")
    args = parser.parse_args()
    out = Path(args.out).expanduser().resolve()

    try:
        html, short_hash, css_n, js_n = build_html()
    except BuildError as exc:
        print(f"构建失败：{exc}")
        return 1

    if args.check:
        existing = current_hash(out)
        if existing == short_hash:
            print(f"构建产物是最新的：{out}")
            return 0
        if existing is None:
            print(f"构建产物不存在或没有构建标记：{out}")
        else:
            print(f"构建产物已过期：{out}（产物 {existing} / 源码 {short_hash}）")
        return 1

    write_atomic(out, html)
    size = out.stat().st_size
    print(f"构建完成：{css_n} 个 CSS / {js_n} 个 JS / {size} 字节")
    print(f"输出：{out}")
    print(f"哈希：{short_hash}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
