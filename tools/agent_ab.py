"""P16.4：真实学习任务 A/B 评测。

对照组 = 2.10.2 的工具集（无 make_plan / recent_wrong_items / 资料写入 / 代码运行），
无自检重写；实验组 = 当前 P16.1–P16.3。

用法（会调用真实模型、产生费用）：
    .venv/Scripts/python.exe -X utf8 tools/agent_ab.py --out docs/P16.4-AB评测.md

安全：每次评测都在临时数据根里跑，不碰 D:\\学习系统；设置文件只复制到临时目录。
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from learnsys import config as app_config
from learnsys import store
from learnsys.agent import cost as agent_cost
from learnsys.agent import loop, prompts, selfcheck, tools
from learnsys.llm.config import load_config

from tools.baseline_prompt import (BASE_SYSTEM as _BASELINE_BASE_SYSTEM,
                                   CONCISE_ADDITION as _BASELINE_CONCISE_ADDITION,
                                   DEEP_ADDITION as _BASELINE_DEEP_ADDITION)

CONTROL_TOOLS = {
    "search_records", "today_summary", "read_attachment", "ocr_image",
    "search_materials", "read_material", "get_cet6_context",
    "save_wrongbook", "save_memory", "forget_memory",
}

TASKS = [
    {"id": "today", "category": "今日", "question": "看今天的学习概况，告诉我问答多少条、错题本有几题。",
     "groups": [r"问答", r"错题"], "expect_tools": ["today_summary"]},
    {"id": "records", "category": "记录", "question": "我之前问过「TCP 三次握手」什么？把当时的回答要点说出来。",
     "groups": [r"三次", r"SYN", r"ACK"], "expect_tools": ["search_records"]},
    {"id": "stack", "category": "资料", "question": "资料《数据结构讲义》里栈和队列的区别是什么？标出页码。",
     "groups": [r"后进先出|LIFO", r"先进先出|FIFO", r"第\s*2\s*页|第\s*1[–\-~、]\s*2\s*页"],
     "expect_tools": ["search_materials", "read_material"]},
    {"id": "congestion", "category": "资料", "question": "《计算机网络》里拥塞控制的四种算法是什么？",
     "groups": [r"慢启动|慢开始", r"拥塞避免", r"快重传", r"快恢复"],
     "expect_tools": ["search_materials", "read_material"]},
    {"id": "wrong", "category": "错题", "question": "我最近错了哪些题？只列题号和题目。",
     "groups": [r"错题\s*#?\s*1|#1", r"栈和队列", r"顺序表"],
     "expect_tools": ["recent_wrong_items"], "new_capability": True},
    {"id": "cross", "category": "综合", "question": "找出我最近错的题，读出对应资料段落，再出 2 道变式题（不给答案）。",
     "groups": [r"错题\s*#?\s*1|#1", r"数据结构讲义|资料", r"变式|想一想题"],
     "expect_tools": ["recent_wrong_items", "search_materials", "read_material"],
     "new_capability": True},
    {"id": "cet6", "category": "六级", "question": "我上次六级精听循环的是哪一句？循环了几次？",
     "groups": [r"第\s*2\s*句|第2句", r"3\s*次|三次"],
     "expect_tools": ["get_cet6_context"]},
    {"id": "save_note", "category": "写入", "question": "把「栈是后进先出，队列是先进先出」整理成一份资料笔记保存，标题《栈笔记》。",
     "groups": [r"已保存|资料\s*#|保存"], "side_effect": "material_note",
     "expect_tools": ["save_material_note"], "new_capability": True},
    {"id": "cpp_run", "category": "代码", "question": "用 C++ 写一个最小程序输出 3 的阶乘并运行给我看。",
     "groups": [r"(^|\D)6(\D|$)"], "expect_tools": ["run_code"],
     "require_tool": "run_code", "new_capability": True},
    {"id": "python_run", "category": "代码",
     "question": "用 Python 循环打印 1 到 3 的平方，每个平方数单独一行，并运行给我看。",
     "groups": [r"^[^\d\n]*1\s*$", r"^[^\d\n]*4\s*$", r"^[^\d\n]*9\s*$"],
     "expect_tools": ["run_code"], "require_tool": "run_code",
     "new_capability": True},
    {"id": "deadlock", "category": "知识", "question": "解释一下什么是死锁，给一个最小例子。",
     "groups": [r"互相等待|循环等待", r"资源"]},
    {"id": "weak", "category": "复盘", "question": "把我今天问过的问题串一遍，找出重复出现的薄弱点。",
     "groups": [r"TCP", r"栈"], "expect_tools": ["search_records", "today_summary"]},
    {"id": "absent", "category": "诚实", "question": "资料《数据结构讲义》里有没有提到「红黑树」？没有就直说。",
     "groups": [r"没有|未提到|没提到"], "forbid": [r"红黑树在资料"],
     "expect_tools": ["search_materials"]},
    {"id": "compare", "category": "综合", "question": "对比《数据结构讲义》和《计算机网络》里各自最重要的一个概念，并说明为什么。",
     "groups": [r"栈|队列|后进先出", r"TCP|三次握手|拥塞", r"资料"],
     "expect_tools": ["search_materials"]},
]


def _seed_settings(root: pathlib.Path, source: pathlib.Path) -> dict:
    """复制真实设置（含 key）到临时根，并写入用于评测的单价。"""
    data = {}
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    agent = data.setdefault("agent", {})
    agent.pop("data_root", None)
    agent.pop("routes", None)   # 两组必须跑同一个模型，否则 A/B 结论失真
    agent["speed"] = "balanced"
    agent["thinking"] = False
    for key, value in (("price_input", 1.0), ("price_output", 2.0),
                       ("price_cache_read", 0.1), ("currency", "USD")):
        agent.setdefault(key, value)
    root.mkdir(parents=True, exist_ok=True)
    (root / "设置.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _seed_db(root: pathlib.Path) -> dict:
    conn = store.connect(root / "learning.db")
    ids = {}
    try:
        data_id, _ = store.add_material(
            conn, title="数据结构讲义", kind="note", pages=3,
            body=("第一章 线性表\n\n顺序表用连续内存存储，插入平均移动 n/2 个元素。\f"
                  "第二章 栈和队列\n\n栈是后进先出（LIFO），只能在栈顶插入和删除；"
                  "队列是先进先出（FIFO），队尾入队、队头出队。\f"
                  "第三章 树\n\n二叉树每个结点最多两个子结点。"))
        net_id, _ = store.add_material(
            conn, title="计算机网络", kind="note", pages=2,
            body=("第一章 传输层\n\nTCP 三次握手：客户端发送 SYN；服务端回复 SYN+ACK；"
                  "客户端再发送 ACK。\f"
                  "第二章 拥塞控制\n\n四种算法：慢启动、拥塞避免、快重传、快恢复。"))
        ids["data"] = data_id
        ids["net"] = net_id
        w1, _ = store.add_wrong_item(
            conn, question="栈和队列的出入顺序有什么区别？",
            answer="栈后进先出，队列先进先出", my_answer="栈是先进先出",
            source="quiz", source_id="quiz:seed:1", material_id=data_id)
        store.add_wrong_item(
            conn, question="顺序表的插入平均要移动多少元素？",
            answer="n/2", my_answer="0", source="quiz",
            source_id="quiz:seed:2", material_id=data_id)
        store.add_wrong_item(
            conn, question="TCP 三次握手的第二步发送什么标志？",
            answer="SYN+ACK", my_answer="ACK", source="quiz",
            source_id="quiz:seed:3", material_id=net_id)
        ids["w1"] = w1
        today = datetime.date.today().isoformat()
        store.add_ask(conn, "TCP 三次握手过程的第二步是什么？",
                      "服务端回复 SYN+ACK，确认客户端的 SYN 并同步自己的序号。",
                      1200, "deepseek-v4-pro")
        store.add_ask(conn, "栈和队列有什么区别？",
                      "栈后进先出（LIFO），队列先进先出（FIFO）。",
                      900, "deepseek-v4-pro")
        store.add_ask(conn, "顺序表插入为什么要移动元素？",
                      "要为新元素腾位置，平均移动 n/2 个元素。",
                      1100, "deepseek-v4-pro")
        conn.execute(
            "INSERT INTO transcripts (session_id, ts_start, ts_end, text) "
            "VALUES (1, ?, ?, ?)",
            (f"{today} 10:00:00", f"{today} 10:00:20",
             "老师说 TCP 三次握手第二步是 SYN+ACK，考试常考。"))
        conn.commit()
        store.upsert_cet6_progress(
            conn, paper_id="paper-1", paper_title="2023年12月六级听力",
            section="Section A", item="News Report 1",
            rows=[
                {"sentence": 1, "en": "The company announced a new policy.",
                 "tags": "", "loops": 0, "plays": 1},
                {"sentence": 2, "en": "It is a turning point for the industry.",
                 "tags": ["连读"], "note": "这里连读没听出来",
                 "loops": 3, "plays": 5},
                {"sentence": 3, "en": "Analysts remain cautious.",
                 "tags": "", "loops": 0, "plays": 1},
            ],
            done=[1])
    finally:
        conn.close()
    return ids


@contextlib.contextmanager
def _activate(root: pathlib.Path, settings: dict):
    """让 load_config 读到这个临时数据根（config 模块是全局缓存）。"""
    old = (app_config.USER, app_config.DATA_ROOT, app_config.SETTINGS_FILE)
    app_config.USER = settings
    app_config.DATA_ROOT = root
    app_config.SETTINGS_FILE = root / "设置.json"
    try:
        yield
    finally:
        app_config.USER, app_config.DATA_ROOT, app_config.SETTINGS_FILE = old



@contextlib.contextmanager
def _control_mode(enabled: bool):
    if not enabled:
        yield
        return
    original_schemas = tools.schemas_for
    original_verify = selfcheck.verify
    original_base = prompts.BASE_SYSTEM
    original_concise = prompts.CONCISE_ADDITION
    original_deep = prompts.DEEP_ADDITION
    original_examples = prompts.STYLE_EXAMPLES

    def schemas_for(mode="explain", *, use_tools=True):
        schemas = original_schemas(mode, use_tools=use_tools)
        if not schemas:
            return schemas
        return [schema for schema in schemas
                if schema.get("name") in CONTROL_TOOLS]

    tools.schemas_for = schemas_for
    selfcheck.verify = lambda *args, **kwargs: []
    prompts.BASE_SYSTEM = _BASELINE_BASE_SYSTEM
    prompts.CONCISE_ADDITION = _BASELINE_CONCISE_ADDITION
    prompts.DEEP_ADDITION = _BASELINE_DEEP_ADDITION
    prompts.STYLE_EXAMPLES = ""
    try:
        yield
    finally:
        tools.schemas_for = original_schemas
        selfcheck.verify = original_verify
        prompts.BASE_SYSTEM = original_base
        prompts.CONCISE_ADDITION = original_concise
        prompts.DEEP_ADDITION = original_deep
        prompts.STYLE_EXAMPLES = original_examples


def _score(task: dict, answer: str, haystack: str, side_ok: bool,
           used_tools: set[str], failed_tools: set[str]) -> float:
    if task.get("side_effect") == "material_note":
        return 1.0 if side_ok else 0.0
    required = task.get("require_tool")
    if required and (required not in used_tools or required in failed_tools):
        return 0.0
    groups = task.get("groups") or []
    matched = sum(1 for pattern in groups
                  if re.search(pattern, haystack, re.IGNORECASE | re.MULTILINE))
    score = matched / len(groups) if groups else 1.0
    for pattern in task.get("forbid") or []:
        if re.search(pattern, haystack, re.IGNORECASE):
            score = max(0.0, score - 0.5)
    return round(score, 2)


def _note_saved(root: pathlib.Path) -> bool:
    conn = store.connect(root / "learning.db")
    try:
        for item in store.list_materials(conn):
            if "栈笔记" in (item.get("title") or ""):
                detail = store.get_material(conn, item["id"]) or {}
                if "后进先出" in (detail.get("body") or ""):
                    return True
        return False
    finally:
        conn.close()


def _run_one(task: dict, root: pathlib.Path, settings: dict,
             control: bool) -> dict:
    with _activate(root, settings):
        cfg = load_config()
        started = time.monotonic()
        first_ms = None
        events = []
        answer = ""
        error = ""
        outputs = []
        with _control_mode(control):
            try:
                for event in loop.run(
                        loop.AgentRequest(task["question"], mode="explain"),
                        cfg=cfg, confirm=lambda *args: True):
                    if first_ms is None and event.kind in ("text", "thinking"):
                        first_ms = int((time.monotonic() - started) * 1000)
                    events.append(event)
                    if event.kind == "done":
                        answer = str(event.data.get("text") or "")
                    elif event.kind == "error":
                        error = event.text
                    elif event.kind == "tool_end":
                        data = event.data or {}
                        outputs.append(str(data.get("preview") or ""))
                        if data.get("output"):
                            outputs.append(str(data["output"]))
            except Exception as exc:
                error = f"评测异常：{exc}"
                traceback.print_exc()
        total_ms = int((time.monotonic() - started) * 1000)
        done = next((event for event in events if event.kind == "done"), None)
        usage = done.data.get("usage") if done else {}
        counts = agent_cost.normalize_usage(usage)
        amount, currency, _ = agent_cost.estimate(usage, cfg)
        tool_names = [event.data.get("name") for event in events
                      if event.kind == "tool_start"]
        failed_tools = {event.data.get("name") for event in events
                        if event.kind == "tool_end"
                        and event.data.get("ok") is False}
        plan = [event for event in events if event.kind == "plan"]
        checks = [event.data for event in events if event.kind == "check"]
        side_ok = (_note_saved(root)
                   if task.get("side_effect") == "material_note" else True)
        haystack = answer + "\n" + "\n".join(outputs)
        return {
            "task": task["id"], "category": task["category"],
            "variant": "control" if control else "experiment",
            "score": _score(task, answer, haystack, side_ok,
                            set(tool_names), failed_tools),
            "first_ms": first_ms or total_ms, "total_ms": total_ms,
            "tools": tool_names, "tool_calls": len(tool_names),
            "plan": bool(plan), "check_ok": (checks[-1].get("ok")
                                             if checks else None),
            "tokens": counts["total_tokens"],
            "prompt_tokens": counts["prompt_tokens"],
            "completion_tokens": counts["completion_tokens"],
            "cache_read_tokens": counts["cache_read_tokens"],
            "cost": amount, "currency": currency,
            "model_calls": (done.data.get("model_calls") if done else 0),
            "error": error, "answer": answer,
        }


def _avg(values):
    return round(sum(values) / len(values), 2) if values else 0.0


def _summary(rows: list[dict]) -> dict:
    return {
        "score": _avg([row["score"] for row in rows]),
        "first_ms": _avg([row["first_ms"] for row in rows]),
        "total_ms": _avg([row["total_ms"] for row in rows]),
        "tool_calls": _avg([row["tool_calls"] for row in rows]),
        "tokens": _avg([row["tokens"] for row in rows]),
        "cost": round(sum(row["cost"] for row in rows), 6),
        "errors": sum(1 for row in rows if row["error"]),
    }


def _report(rows: list[dict], settings_source: pathlib.Path,
            started_at: str) -> str:
    control = [row for row in rows if row["variant"] == "control"]
    experiment = [row for row in rows if row["variant"] == "experiment"]
    by_id = {task["id"]: task for task in TASKS}
    common_ids = {task["id"] for task in TASKS
                  if not task.get("new_capability")}
    common_control = [row for row in control if row["task"] in common_ids]
    common_experiment = [row for row in experiment if row["task"] in common_ids]
    new_experiment = [row for row in experiment if row["task"] not in common_ids]

    lines = [
        "# P16.4 真实任务 A/B 评测",
        "",
        f"生成时间：{started_at}",
        "对照组：2.10.2 工具集（无 make_plan / recent_wrong_items / 资料写入 / 代码运行），"
        "无自检重写。实验组：P16.1–P16.3。",
        "两个组使用同一模型、同一 `balanced` 速度档、同一份种子数据；每次都在独立临时数据根运行。",
        "",
        "## 汇总",
        "",
        "| 指标 | 对照组 | 实验组 |",
        "|---|---:|---:|",
    ]
    control_summary = _summary(control)
    experiment_summary = _summary(experiment)
    for label, key in (("正确性（0–1）", "score"), ("首 token（ms）", "first_ms"),
                       ("总耗时（ms）", "total_ms"), ("工具调用（次）", "tool_calls"),
                       ("tokens", "tokens"), ("成本（USD，按假设单价）", "cost"),
                       ("错误轮数", "errors")):
        lines.append(f"| {label} | {control_summary[key]} | {experiment_summary[key]} |")
    lines += [
        "",
        "只含有对照组也能做的任务（排除新增能力任务）：",
        "",
        "| 指标 | 对照组 | 实验组 |",
        "|---|---:|---:|",
    ]
    cc, ce = _summary(common_control), _summary(common_experiment)
    for label, key in (("正确性（0–1）", "score"), ("首 token（ms）", "first_ms"),
                       ("总耗时（ms）", "total_ms"), ("工具调用（次）", "tool_calls"),
                       ("tokens", "tokens"), ("成本（USD）", "cost"),
                       ("错误轮数", "errors")):
        lines.append(f"| {label} | {cc[key]} | {ce[key]} |")
    lines += ["", f"新增能力任务（只有实验组有工具）：正确性 "
                  f"{_summary(new_experiment)['score']:.2f}，"
                  f"平均总耗时 {_summary(new_experiment)['total_ms']:.0f} ms。", ""]

    lines += ["## 逐任务", "",
              "| 任务 | 类别 | 对照组正确性 | 实验组正确性 | 对照耗时 | 实验耗时 | 对照工具 | 实验工具 |",
              "|---|---|---:|---:|---:|---:|---|---|"]
    exp_by_id = {row["task"]: row for row in experiment}
    for row in control:
        exp = exp_by_id.get(row["task"], {})
        lines.append(
            f"| {row['task']} | {row['category']} | {row['score']:.2f} | "
            f"{exp.get('score', 0):.2f} | {row['total_ms']} ms | "
            f"{exp.get('total_ms', 0)} ms | {', '.join(row['tools']) or '—'} | "
            f"{', '.join(exp.get('tools') or []) or '—'} |")

    lines += ["", "## 结论", ""]
    common_ok = ce["score"] >= cc["score"] - 0.05
    overhead_ratio = (ce["total_ms"] / cc["total_ms"]) if cc["total_ms"] else 1.0
    overhead_ok = overhead_ratio <= 1.6 or (ce["total_ms"] - cc["total_ms"]) <= 6000
    if common_ok and experiment_summary["score"] > control_summary["score"] and overhead_ok:
        lines.append(
            "**保留默认开启。** 在两组都能做的任务上正确性没有下降，新增能力任务明显提升；"
            f"公共任务总耗时是对照组的 {overhead_ratio:.2f} 倍，在可接受范围内。")
    elif common_ok and not overhead_ok:
        lines.append(
            "**正确性不降，但公共任务耗时偏高。** 建议把「计划/自检」做成设置开关，"
            f"默认仍开、慢机器可关（公共任务耗时是对照组的 {overhead_ratio:.2f} 倍）。")
    else:
        lines.append(
            "**正确性没有达到不降的标准。** 不应默认开启；先按逐任务结果定位退步原因，"
            "再决定是否加开关或回退。")
    lines.append("")
    lines.append("假设单价：输入 1.0 / 输出 2.0 / 缓存命中 0.1（USD 每百万 token），"
                 "仅用于同口径比较，不代表真实账单。")
    lines.append("")
    lines.append("## 逐任务回答（前 240 字，供人工复核）")
    lines.append("")
    for task in TASKS:
        lines.append(f"### {task['id']} · {task['question']}")
        lines.append("")
        for row in rows:
            if row["task"] != task["id"]:
                continue
            label = "对照组" if row["variant"] == "control" else "实验组"
            answer = " ".join((row["answer"] or row["error"] or "（空）").split())
            lines.append(f"- **{label}**（{row['score']:.2f}）：{answer[:240]}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", default=str(app_config.SETTINGS_FILE),
                        help="真实设置文件（只复制，不修改）")
    parser.add_argument("--out", default="docs/P16.4-AB评测.md")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    settings_source = pathlib.Path(args.settings)
    tasks = TASKS[:args.limit] if args.limit else TASKS
    started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict] = []
    roots = {}
    settings = {}
    try:
        for variant in ("control", "experiment"):
            root = pathlib.Path(tempfile.mkdtemp(prefix=f"learnsys-ab-{variant}-"))
            roots[variant] = root
            settings[variant] = _seed_settings(root, settings_source)
            _seed_db(root)
        for index, task in enumerate(tasks, 1):
            for variant in ("control", "experiment"):
                print(f"[{index}/{len(tasks)}] {variant:10s} {task['id']} …",
                      flush=True)
                row = _run_one(task, roots[variant], settings[variant],
                               control=(variant == "control"))
                rows.append(row)
                plan = " 计划" if row["plan"] else ""
                print(f"    正确性 {row['score']:.2f} | "
                      f"首字 {row['first_ms']}ms | 总 {row['total_ms']}ms | "
                      f"工具 {row['tool_calls']}{plan} | tokens {row['tokens']} | "
                      f"${row['cost']:.4f} | {row['error'][:60]}", flush=True)
    finally:
        if args.json:
            pathlib.Path(args.json).write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        report = _report(rows, settings_source, started_at) if rows else ""
        if args.out and report:
            out = pathlib.Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(report, encoding="utf-8")
            print(f"\n报告：{out}")
        for root in roots.values():
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
