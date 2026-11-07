"""Agent 任务级评测命令行：离线可作答性体检 + 在线真实模型评测。

口径与判分在 `agent_eval_core.py`；这里只负责临时快照、报告、表格和参数。

用法：
    python tools/agent_eval.py                  # 离线体检
    python tools/agent_eval.py --live           # 真实模型评测（需预算）
    python tools/agent_eval.py --all            # 两段都跑
    python tools/agent_eval.py --case due-reviews --case mastery
    python tools/agent_eval.py --save-baseline  # 更新基线
    python tools/agent_eval.py --db path/to/learning.db
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import agent_eval_core as core

SUITE_PATH = core.SUITE_PATH
BASELINE_PATH = core.BASELINE_PATH
REPORT_DIR = ROOT / "eval" / "agent"


def _width(text: str) -> int:
    """按终端显示宽度算中文字符（东亚洲宽字符占两格）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in str(text))


def _pad(text: str, width: int) -> str:
    text = str(text)
    return text + " " * max(0, width - _width(text))


def _snapshot_db(source: pathlib.Path, work: pathlib.Path) -> pathlib.Path:
    """把源库一致地复制到工作目录；源库不存在就建一个空库。"""
    target = work / "learning.db"
    if source.is_file():
        src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    else:
        from learnsys import store
        store.connect(target).close()
    return target


def _copy_archive(source_root: pathlib.Path, work: pathlib.Path) -> int:
    """复制封存的对话总汇（只复制 md，不复制整个资料库）。"""
    folder = source_root / "记忆档案"
    if not folder.is_dir():
        return 0
    target = work / "记忆档案"
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in folder.glob("*.md"):
        shutil.copy2(item, target / item.name)
        count += 1
    return count


def _write_report(mode: str, results: list[dict], extra: dict | None = None) -> pathlib.Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"{mode}-{stamp}.json"
    payload = {
        "mode": mode,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
        **(extra or {}),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    shutil.copy2(path, REPORT_DIR / f"latest-{mode}.json")
    return path


def _render_offline(results: list[dict], baseline_lines: list[str]) -> str:
    lines = ["", "=== Agent 评测 · 离线可作答性（0 次模型调用）===", ""]
    lines.append(f"{_pad('用例', 24)}{_pad('数据域', 14)}{_pad('状态', 8)}"
                 f"{_pad('耗时', 8)}字符")
    for item in results:
        lines.append(f"{_pad(item['id'], 24)}{_pad(item['domain'], 14)}"
                     f"{_pad(item['status'], 8)}{_pad(str(item['ms']) + 'ms', 8)}"
                     f"{item['chars']}")
        for detail in item["details"]:
            lines.append(f"    - {detail}")
    passed = sum(1 for item in results if item["status"] == "通过")
    empty = sum(1 for item in results if item["status"] == "空数据")
    failed = sum(1 for item in results if item["status"] == "失败")
    lines.append("")
    lines.append(f"汇总：通过 {passed} · 空数据 {empty} · 失败 {failed} · 共 {len(results)}")
    lines.extend(baseline_lines)
    return "\n".join(lines)


def _render_live(results: list[dict], baseline_lines: list[str]) -> str:
    lines = ["", "=== Agent 评测 · 在线真实模型 ===", ""]
    lines.append(f"{_pad('用例', 24)}{_pad('结果', 8)}{_pad('工具', 6)}"
                 f"{_pad('步骤', 6)}{_pad('耗时', 8)}花费")
    for item in results:
        lines.append(f"{_pad(item['id'], 24)}{_pad('通过' if item['pass'] else '未通过', 8)}"
                     f"{_pad(str(len(item['tools'])), 6)}{_pad(str(item['steps']), 6)}"
                     f"{_pad(str(item['ms']) + 'ms', 8)}¥{item['cost']:.4f}")
        for reason in item["reasons"]:
            lines.append(f"    - {reason}")
        if item["tools"]:
            lines.append(f"    工具：{'、'.join(item['tools'])}")
    passed = sum(1 for item in results if item["pass"])
    lines.append("")
    lines.append(f"汇总：通过 {passed} / 未通过 {len(results) - passed} · 共 {len(results)}")
    lines.extend(baseline_lines)
    return "\n".join(lines)


def _select(cases: list[dict], wanted: list[str] | None) -> list[dict]:
    if not wanted:
        return cases
    wanted_set = set(wanted)
    selected = [case for case in cases if case["id"] in wanted_set]
    missing = wanted_set - {case["id"] for case in selected}
    if missing:
        raise SystemExit("题库里没有这些用例：" + "、".join(sorted(missing)))
    return selected


def _prepare_work(data_root: pathlib.Path, db: pathlib.Path | None) -> tuple[pathlib.Path, dict]:
    work = pathlib.Path(tempfile.mkdtemp(prefix="learnsys-eval-"))
    source_db = db or (data_root / "learning.db")
    _snapshot_db(source_db, work)
    archived = _copy_archive(data_root, work)
    return work, {"db": str(source_db), "archive_files": archived}


def _budget_blocked(cfg) -> str | None:
    from learnsys.agent import budget
    return budget.check(cfg)


def _run_offline(cases: list[dict], work: pathlib.Path, meta: dict,
                 save_baseline: bool) -> int:
    results = [core.run_offline_case(case, work) for case in cases
               if case.get("offline")]
    if not results:
        print("题库里没有离线段用例。")
        return 0
    report = _write_report("offline", results, meta)
    print(_render_offline(results, core.compare("offline", results)))
    print(f"报告：{report.relative_to(ROOT)}")
    if save_baseline:
        print(f"基线已更新：{core.save_baseline('offline', results)}")
    return int(any(item["status"] == "失败" for item in results))


def _run_live(cases: list[dict], work: pathlib.Path, cfg, meta: dict,
              save_baseline: bool) -> int:
    blocked = _budget_blocked(cfg)
    if blocked:
        print("\n在线评测没有开始：" + blocked)
        return 2
    results = []
    for case in [case for case in cases if case.get("live")]:
        obs = core.collect_live(case, dataclasses.replace(cfg, data_root=work))
        ok, reasons = core.grade_live(case, obs)
        results.append({
            "id": obs["id"], "domain": obs["domain"], "pass": ok,
            "reasons": reasons, "tools": obs["tools"],
            "steps": obs["steps"], "tool_calls": obs["tool_calls"],
            "cost": obs["cost"], "ms": obs["ms"],
        })
        print(f"[{'通过' if ok else '未通过'}] {case['id']}")
        if not ok:
            print("    " + "；".join(reasons))
    if not results:
        print("题库里没有在线段用例。")
        return 0
    report = _write_report("live", results, meta)
    print(_render_live(results, core.compare("live", results)))
    print(f"报告：{report.relative_to(ROOT)}")
    if save_baseline:
        print(f"基线已更新：{core.save_baseline('live', results)}")
    return int(any(not item["pass"] for item in results))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="学习工作台 Agent 任务级评测（离线可作答性 / 在线真实模型）")
    parser.add_argument("--live", action="store_true", help="跑真实模型评测（消耗模型调用）")
    parser.add_argument("--all", action="store_true", help="离线和在线都跑")
    parser.add_argument("--case", action="append", default=None,
                        help="只跑指定用例 id，可重复")
    parser.add_argument("--db", type=pathlib.Path, default=None,
                        help="指定 learning.db；默认用当前数据根的生产库快照")
    parser.add_argument("--data-root", type=pathlib.Path, default=None,
                        help="数据根目录；默认取当前设置")
    parser.add_argument("--suite", type=pathlib.Path, default=SUITE_PATH,
                        help="题库 JSON 路径")
    parser.add_argument("--save-baseline", action="store_true", help="把本次结果存为基线")
    parser.add_argument("--list", action="store_true", help="只列出题库里的用例")
    parser.add_argument("--keep", action="store_true", help="保留临时工作目录，便于排查")
    args = parser.parse_args(argv)

    suite = core.load_suite(args.suite)
    cases = _select(suite["cases"], args.case)
    if args.list:
        for case in cases:
            print(f"{case['id']:<24} {case.get('domain', ''):<14} {case.get('question', '')}")
        return 0

    from learnsys.llm.config import load_config
    cfg = load_config()
    if args.live and not args.all:
        blocked = _budget_blocked(cfg)
        if blocked:
            print("在线评测没有开始：" + blocked)
            return 2
    data_root = args.data_root or pathlib.Path(cfg.data_root)
    work, meta = _prepare_work(data_root, args.db)
    print(f"工作快照：{work}")
    print(f"源库：{meta['db']}；复制封存档案 {meta['archive_files']} 个")

    exit_code = 0
    try:
        if not args.live or args.all:
            exit_code = max(exit_code, _run_offline(
                cases, work, meta, args.save_baseline))
        if args.live or args.all:
            exit_code = max(exit_code, _run_live(
                cases, work, cfg, meta, args.save_baseline))
    finally:
        if args.keep:
            print(f"临时目录已保留：{work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
