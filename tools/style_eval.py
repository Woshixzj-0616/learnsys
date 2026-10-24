"""回答风格抽样评测：20 道题跑真实模型，统计篇幅、代码块、结尾提问。

用法（会调用真实模型、产生费用）：
    .venv/Scripts/python.exe -X utf8 tools/style_eval.py
    .venv/Scripts/python.exe -X utf8 tools/style_eval.py --speed deep --limit 5

每题用 `tools/agent_cli.py --json-out` 跑一遍，本脚本只负责编排和统计，
不重复实现 Agent 调用。结果写到 `eval/style/`（临时目录，可随时删）。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "agent_cli.py"
PYTHON = sys.executable

# cap：该档的字数上限（None = 不限）；0 表示只检查触发结果，不查字数。
QUESTIONS = [
    {"id": "01", "category": "事实", "cap": 300,
     "q": "dirent 的全名是什么？"},
    {"id": "02", "category": "事实", "cap": 300,
     "q": "RBAC 的全名是什么？"},
    {"id": "03", "category": "事实", "cap": 300,
     "q": "find 命令怎么用？"},
    {"id": "04", "category": "排错", "cap": 1500,
     "q": "dirent.h 需要 apt 安装吗？为什么我这里找不到？"},
    {"id": "05", "category": "事实", "cap": 300,
     "q": "printf 能直接打印 char* 类型吗？"},
    {"id": "06", "category": "机制", "cap": 800,
     "q": "inode、dirent、DIR、FILE 这几个数据结构之间是什么关系？"},
    {"id": "07", "category": "机制", "cap": 800,
     "q": "内存里的块、磁盘上的块和 cache，有什么区别？"},
    {"id": "08", "category": "机制", "cap": 800,
     "q": "挂载是什么？"},
    {"id": "09", "category": "机制", "cap": 800,
     "q": "硬链接为什么不能跨文件系统？是因为 inode 表每个文件系统一个吗？"},
    {"id": "10", "category": "机制", "cap": 800,
     "q": "挂载之后把原来的东西覆盖了，不是很荒谬吗？"},
    {"id": "11", "category": "排错", "cap": 1500, "allow_code": 2,
     "q": "Dir.c 编译报错：initialization of 'struct DIR' from incompatible pointer type，是什么原因？"},
    {"id": "12", "category": "排错", "cap": 1500,
     "q": "你刚才的回答输出被截断了，是怎么回事？"},
    {"id": "13", "category": "详细", "cap": None,
     "q": "具体说说 RBAC 为什么这样设计，最好来一些对比。"},
    {"id": "14", "category": "详细", "cap": None,
     "q": "我感觉自己没有文件系统的基础知识，系统说说文件系统的基础知识。"},
    {"id": "15", "category": "代码触发", "cap": None, "expect_code": True,
     "q": "用 C 写一个判断链表是否有环的函数，只要核心代码。"},
    {"id": "16", "category": "代码触发", "cap": None, "expect_code": True,
     "q": "给我看看 dirent 结构体的源码长什么样。"},
    {"id": "17", "category": "出题触发", "cap": None, "expect_quiz": True,
     "q": "出 3 道 TCP 的题考我，先别给答案。"},
    {"id": "18", "category": "出题触发", "cap": None, "expect_quiz": True,
     "q": "考考我文件系统，一次一题。"},
    {"id": "19", "category": "类比", "cap": 800,
     "q": "用生活里的例子解释一下挂载。"},
    {"id": "20", "category": "偏好", "cap": 60,
     "q": "你以后用 C 写。",
     "history": [["用 C++ 写一个栈，给完整代码",
                  "```cpp\n#include <vector>\nstruct Stack { std::vector<int> v; };\n```"]]},
]


def _run(item: dict, speed: str, out_dir: pathlib.Path, timeout: float,
         env: dict) -> dict:
    out = out_dir / f"{item['id']}.json"
    command = [PYTHON, "-X", "utf8", str(CLI), item["q"],
               "--mode", "explain", "--speed", speed, "--json-out", str(out)]
    history_path = None
    if item.get("history"):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(item["history"], handle, ensure_ascii=False)
        handle.close()
        history_path = pathlib.Path(handle.name)
        command += ["--history-file", str(history_path)]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", timeout=timeout,
                                env=env)
        if result.returncode != 0 or not out.exists():
            return {"error": (result.stderr or result.stdout)[-400:]}
        record = json.loads(out.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        return {"error": f"超时 {timeout:.0f} 秒"}
    finally:
        if history_path:
            history_path.unlink(missing_ok=True)
    record["category"] = item["category"]
    record["cap"] = item["cap"]
    record["expect_code"] = bool(item.get("expect_code"))
    record["expect_quiz"] = bool(item.get("expect_quiz"))
    record["allow_code"] = int(item.get("allow_code") or 0)
    return record


def _quiz_ok(answer: str) -> bool:
    """讲解模式下的出题：有题、没答案（不要求测验模式的【第N题】标记）。"""
    has_question = bool(re.search(r"[？?]", answer))
    has_answer = bool(re.search(r"【批改】|答案[：:]|正确答案", answer))
    return has_question and not has_answer


def _first_line(answer: str) -> str:
    for line in str(answer or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _summary(rows: list[dict]) -> tuple[list[str], int]:
    lines = ["| # | 类别 | 字数 | 上限 | 代码块 | 结尾提问 | 判定 | 耗时 |",
             "|---|---|---|---|---|---|---|---|"]
    failures = 0
    for row in rows:
        if row.get("error"):
            failures += 1
            lines.append(f"| {row['id']} | {row['category']} | — | — | — | — | "
                         f"失败：{row['error'][:60]} | — |")
            continue
        chars = row["chars_total"]
        cap = row["cap"]
        measured = chars
        if row["category"] == "偏好":
            # 偏好只要求首行确认；后面的「没有执行」是 CLI 无人确认的正常提示
            measured = len(_first_line(row["answer"]))
        problems = []
        if cap is not None and measured > cap * 1.2:
            problems.append(f"超长 {measured}>{cap}")
        if row["expect_code"] and not row["code_blocks"]:
            problems.append("没给代码")
        allowed_code = row.get("allow_code", 0)
        if not row["expect_code"] and row["code_blocks"] > allowed_code:
            problems.append("多给代码")
        if row["expect_quiz"] and not _quiz_ok(row["answer"]):
            problems.append("没按出题格式")
        if not row["expect_quiz"] and row["has_thinking_section"]:
            problems.append("结尾提问")
        if problems:
            failures += 1
        shown = f"{chars}（首行 {measured}）" if measured != chars else str(chars)
        lines.append(
            f"| {row['id']} | {row['category']} | {shown} | "
            f"{cap if cap is not None else '不限'} | {row['code_blocks']} | "
            f"{'有' if row['has_thinking_section'] else '无'} | "
            f"{'、'.join(problems) or '合格'} | {row['latency_ms'] / 1000:.1f}s |")
    return lines, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="回答风格抽样评测")
    parser.add_argument("--speed", default="balanced",
                        choices=["fast", "balanced", "deep"])
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out-dir", default=str(ROOT / "eval" / "style"))
    parser.add_argument("--reuse", action="store_true",
                        help="不调用模型，直接用 out-dir 里已有的 JSON 重新统计")
    args = parser.parse_args()

    items = QUESTIONS[:args.limit] if args.limit else QUESTIONS
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 用临时数据根跑：偏好题会调用 save_memory，不能写进真实学习库。
    source = pathlib.Path(os.environ.get("LEARNSYS_DATA_ROOT") or "D:/学习系统")
    temp_root = pathlib.Path(tempfile.mkdtemp(prefix="learnsys-style-"))
    settings = source / "设置.json"
    if settings.exists():
        shutil.copy2(settings, temp_root / "设置.json")
    env = {**os.environ, "LEARNSYS_DATA_ROOT": str(temp_root)}
    print(f"临时数据根：{temp_root}")

    rows = []
    for index, item in enumerate(items, 1):
        print(f"[{index}/{len(items)}] {item['id']} {item['category']}：{item['q']}",
              flush=True)
        reused = out_dir / f"{item['id']}.json"
        if args.reuse and reused.exists():
            row = json.loads(reused.read_text(encoding="utf-8"))
            row["category"] = item["category"]
            row["cap"] = item["cap"]
            row["expect_code"] = bool(item.get("expect_code"))
            row["expect_quiz"] = bool(item.get("expect_quiz"))
            row["allow_code"] = int(item.get("allow_code") or 0)
        else:
            row = _run(item, args.speed, out_dir, args.timeout, env)
        row.setdefault("id", item["id"])
        row.setdefault("category", item["category"])
        rows.append(row)
        if row.get("error"):
            print(f"    ✗ {row['error'][:120]}", flush=True)
        else:
            print(f"    {row['chars_total']} 字 ｜ 代码块 {row['code_blocks']} ｜ "
                  f"{row['latency_ms'] / 1000:.1f}s", flush=True)

    lines, failures = _summary(rows)
    print("\n" + "\n".join(lines))
    ok = [row for row in rows if not row.get("error")]
    by_category: dict[str, list[int]] = {}
    for row in ok:
        by_category.setdefault(row["category"], []).append(row["chars_total"])
    print("\n分类中位数：")
    for category, values in by_category.items():
        print(f"- {category}：{int(statistics.median(values))} 字（{len(values)} 题）")
    print(f"\n不合格 {failures} / {len(rows)}")

    report = out_dir / f"report-{args.speed}.md"
    report.write_text("# 回答风格抽样\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告：{report}")
    shutil.rmtree(temp_root, ignore_errors=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
