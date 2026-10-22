"""把本机六级精听源码同步进仓库 `cet6-src/`（单向快照）。

真源仍是 `D:\\cet6_tool`（日常构建在那里）；仓库这份是**版本兜底**：
试卷、音频、产物、抓取缓存一律不进来。

用法：
    python tools/sync_cet6_src.py            # 复制（只增改，不删除）
    python tools/sync_cet6_src.py --check    # 只检查漂移，返回 1 表示仓库落后

源目录可用环境变量 `CET6_TOOL` 覆盖。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "cet6-src"
SOURCE = pathlib.Path(os.environ.get("CET6_TOOL") or r"D:\cet6_tool")

ROOT_FILES = [
    "build_workbench.py", "split_listening.py", "apply_corrections.py",
    "apply_structural_fixes.py", "workbench_template.html", "文本体检报告.md",
]
TOOL_SUFFIX = ".py"
SKIP_DIRS = {"__pycache__", "_tmp", "_dump", "_web", "_src", "models", "tmpwork"}


def _digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs() -> list[tuple[pathlib.Path, pathlib.Path]]:
    pairs: list[tuple[pathlib.Path, pathlib.Path]] = []
    for rel in ROOT_FILES:
        source = SOURCE / rel
        if source.is_file():
            pairs.append((source, TARGET / rel))
    source_dir = SOURCE / "workbench_src"
    if source_dir.is_dir():
        for item in source_dir.rglob("*"):
            if item.is_file() and not any(part in SKIP_DIRS for part in item.parts):
                pairs.append((item, TARGET / "workbench_src" / item.relative_to(source_dir)))
    proof_dir = SOURCE / "校对"
    if proof_dir.is_dir():
        for item in proof_dir.rglob("*.json"):
            pairs.append((item, TARGET / "校对" / item.relative_to(proof_dir)))
    tools_dir = SOURCE / "校对工具"
    if tools_dir.is_dir():
        for item in tools_dir.glob(f"*{TOOL_SUFFIX}"):
            pairs.append((item, TARGET / "校对工具" / item.name))
    return pairs


def check() -> int:
    if not SOURCE.is_dir():
        print(f"源目录不存在，跳过：{SOURCE}")
        return 0
    stale = []
    for source, target in _pairs():
        if not target.is_file() or _digest(source) != _digest(target):
            stale.append(source.relative_to(SOURCE).as_posix())
    if stale:
        print(f"仓库里的六级源码落后 {len(stale)} 个文件：")
        for rel in stale[:20]:
            print(f"  · {rel}")
        if len(stale) > 20:
            print(f"  …还有 {len(stale) - 20} 个")
        print("运行 `python tools/sync_cet6_src.py` 同步。")
        return 1
    print("六级源码与仓库一致。")
    return 0


def sync() -> int:
    if not SOURCE.is_dir():
        print(f"源目录不存在：{SOURCE}")
        return 1
    copied = 0
    for source, target in _pairs():
        if target.is_file() and _digest(source) == _digest(target):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    print(f"同步完成：{copied} 个文件有更新。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="同步六级精听源码到仓库")
    parser.add_argument("--check", action="store_true", help="只检查，不复制")
    args = parser.parse_args()
    return check() if args.check else sync()


if __name__ == "__main__":
    sys.exit(main())
