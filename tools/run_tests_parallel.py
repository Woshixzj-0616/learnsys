# -*- coding: utf-8 -*-
"""并行跑后端测试：按测试文件分片到多个进程，汇总结果。

用法：
    .venv/Scripts/python tools/run_tests_parallel.py          # 默认 CPU 核数
    .venv/Scripts/python tools/run_tests_parallel.py --jobs 8
    .venv/Scripts/python tools/run_tests_parallel.py --filter review

每个分片用独立进程跑 `unittest`，测试自带的临时库隔离不受影响；
任何一片失败，整体返回非零，并在末尾列出失败分片的输出。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"


def _modules() -> list[str]:
    return sorted(
        f"tests.{path.stem}" for path in TESTS.glob("test_*.py")
        if path.is_file())


def _run_group(index: int, modules: list[str]) -> tuple[int, str, str, float]:
    started = time.time()
    command = [sys.executable, "-X", "utf8", "-m", "unittest", *modules]
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    return index, result.stdout, result.stderr, time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="并行跑后端 unittest")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                        help="并行进程数，默认 CPU 核数")
    parser.add_argument("--filter", default="",
                        help="只跑文件名包含该字符串的测试")
    args = parser.parse_args()

    modules = _modules()
    if args.filter:
        modules = [name for name in modules if args.filter in name]
    if not modules:
        print("没有找到测试。")
        return 1

    jobs = max(1, min(int(args.jobs or 1), len(modules)))
    groups: list[list[str]] = [[] for _ in range(jobs)]
    for index, name in enumerate(modules):
        groups[index % jobs].append(name)

    print(f"并行测试：{len(modules)} 个文件 / {jobs} 个进程")
    started = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(_run_group, index, group)
                   for index, group in enumerate(groups)]
        for future in futures:
            results.append(future.result())

    failed = []
    for index, stdout, stderr, seconds in sorted(results):
        text = (stdout + stderr).strip()
        tail = text.splitlines()[-1] if text else "（无输出）"
        print(f"  分片 {index + 1}: {tail} · {seconds:.1f} 秒")
        if "FAILED" in text or "ERROR" in text:
            failed.append((index, text))

    total = time.time() - started
    if failed:
        print(f"\n失败 {len(failed)} 片，用时 {total:.1f} 秒。")
        for index, text in failed:
            print(f"\n===== 分片 {index + 1} =====")
            print(text[-4000:])
        return 1
    print(f"\n全部通过 · {len(modules)} 个文件 / {jobs} 进程 · {total:.1f} 秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
