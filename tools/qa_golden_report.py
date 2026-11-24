"""P35.0 问答 golden set 回溯基线。

只读 `D:/学习系统/learning.db`，不调模型、不写学习数据。
把 golden set 里的历史问答取出来，按关键词/工具/引用做确定性初筛，
生成 `eval/qa/baseline-*.json` 与 `docs/施工单/P35-基线报告.md`。

用法：
    python tools/qa_golden_report.py
    python tools/qa_golden_report.py --db D:/学习系统/learning.db
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learnsys.agent.selfcheck import cited_web_dates

GOLDEN = ROOT / "docs" / "golden" / "qa-golden-50.json"
REPORT_DIR = ROOT / "eval" / "qa"
MARKDOWN = ROOT / "docs" / "施工单" / "P35-基线报告.md"


def _text_of(content_json: str) -> str:
    try:
        value = json.loads(content_json)
    except Exception:  # noqa: BLE001 —— 历史消息可能是纯文本，解析失败就原样返回
        return str(content_json or "")
    if isinstance(value, dict):
        return str(value.get("text") or "")
    if isinstance(value, str):
        return value
    return ""


def load_answers(conn: sqlite3.Connection, case: dict) -> list[tuple[str, str]]:
    """返回 [(轮次标签, 回答正文)]；按历史顺序。"""
    cur = conn.cursor()
    ids = case.get("source_ask_ids") or []
    if ids:
        out = []
        for ask_id in ids:
            row = cur.execute("select question, answer from asks where id=?", (ask_id,)).fetchone()
            if row:
                out.append((f"ask#{ask_id}", str(row[1] or "")))
        return out
    conv = case.get("conversation_id")
    if conv:
        out = []
        cur2 = conn.cursor()
        for index, row in enumerate(cur2.execute(
                "select content_json from messages where conversation_id=? and role='assistant' order by id",
                (conv,)), 1):
            text = _text_of(row[0])
            if text.strip():
                out.append((f"t{index}", text))
        return out
    return []


def load_questions(conn: sqlite3.Connection, case: dict) -> list[str]:
    """工具匹配用的原始问题：优先 turns，其次从 asks 取原文，最后用题面摘要。"""
    turns = case.get("turns") or []
    if turns:
        return [str(item) for item in turns]
    cur = conn.cursor()
    out = []
    for ask_id in case.get("source_ask_ids") or []:
        row = cur.execute("select question from asks where id=?", (ask_id,)).fetchone()
        if row:
            out.append(str(row[0]))
    return out or [str(case.get("question") or "")]


def load_tools(conn: sqlite3.Connection, question: str) -> list[str]:
    """按问题前 80 字匹配 agent_runs，返回工具名列表。

    agent_runs.question 只存前 200 字，长代码题用 200 字精确匹配容易因
    换行/截断差异落空；前 80 字足够区分同一道题，也能容忍后续差异。
    """
    if not question:
        return []
    cur = conn.cursor()
    row = cur.execute(
        "select trace_json from agent_runs where substr(question,1,80)=? "
        "order by id desc limit 1",
        (question[:80],)).fetchone()
    if not row or not row[0]:
        return []
    try:
        trace = json.loads(row[0])
    except Exception:  # noqa: BLE001 —— 旧 trace 格式不一致时按「没有工具」处理
        return []
    names = []
    for event in trace:
        if event.get("kind") == "tool_start":
            name = str((event.get("data") or {}).get("name") or "")
            if name:
                names.append(name)
    return names


def check_fact(text: str, groups: list[list[str]], must_not: list[str]) -> tuple[bool, bool]:
    # 去掉 Markdown 强调符再比：模型常写「`vector` 没有」，直接找
    # 「vector 没有」会被反引号隔断。
    low = re.sub(r"[`*]+", "", str(text or "")).lower()
    low = " ".join(low.split())
    ok = bool(groups) and all(
        any(alt.lower() in low for alt in group) for group in groups)
    bad = any(item.lower() in low for item in must_not)
    return ok, bad


def check_citation(text: str, kind: str) -> bool:
    text = str(text or "")
    if kind == "material":
        # 施工单 §12：资料类回答要么带 id/页码，要么明确说「资料里没有」。
        if re.search(r"资料[^。\n]{0,24}(?:没有|没找到|未找到|查不到|无相关|暂无)", text):
            return True
        return bool(re.search(r"【资料|资料\s*id|第\s*\d+\s*页|《[^》]+》", text))
    if kind == "wrong":
        return bool(re.search(r"错题\s*#\d+", text))
    if kind == "conversation":
        return bool(re.search(r"\[问答\s*20\d\d|问答\s*20\d\d", text))
    if kind == "web":
        # 施工单 §12：网页类回答必须带 URL + 读取日期（日期要紧贴链接）。
        return bool(re.search(r"https?://", text)) and bool(cited_web_dates(text))
    return True


def evaluate_case(conn: sqlite3.Connection, case: dict) -> dict:
    expected = case.get("expected") or {}
    groups = expected.get("fact_groups") or []
    must_not = expected.get("must_not") or []
    tools_any = expected.get("tools_any") or []
    max_turns = int(expected.get("max_turns") or 1)
    citation = str(expected.get("citation") or "none")

    answers = load_answers(conn, case)
    result = {
        "id": case["id"],
        "category": case["category"],
        "question": case.get("question") or "",
        "answers": len(answers),
        "first_pass_turn": None,
        "final_ok": False,
        "must_not_hit": False,
        "citation_ok": None,
        "tools": [],
        "tools_ok": None,
        "status": "待在线评测",
        "note": case.get("notes") or "",
    }
    if not answers:
        return result

    turn_flags = []
    for label, text in answers:
        ok, bad = check_fact(text, groups, must_not) if groups else (False, False)
        turn_flags.append((label, ok, bad))
        if ok and not bad and result["first_pass_turn"] is None:
            result["first_pass_turn"] = len(turn_flags)
        if bad:
            result["must_not_hit"] = True
    last_text = answers[-1][1]
    if groups:
        result["final_ok"] = bool(turn_flags[-1][1] and not turn_flags[-1][2])
    else:
        result["final_ok"] = True

    if citation != "none":
        result["citation_ok"] = check_citation(last_text, citation)

    # 工具：按 turns / asks 原文匹配 agent_runs
    questions = load_questions(conn, case)
    seen = []
    for question in questions:
        for name in load_tools(conn, question):
            if name not in seen:
                seen.append(name)
    result["tools"] = seen
    if tools_any:
        result["tools_ok"] = any(name in seen for name in tools_any)

    # 判定：代码题以「有没有跑」为主，事实关键词只做辅助；
    # 其余题以事实关键词为主。
    if tools_any:
        if result["tools_ok"]:
            result["status"] = "通过"
        elif seen:
            result["status"] = "未通过"
        else:
            result["status"] = "人工复核"
            result["note"] = (result["note"] + "；未匹配到工具轨迹，需人工核对是否跑过").strip("；")
    elif groups and result["first_pass_turn"] is not None:
        if result["first_pass_turn"] <= max_turns and not result["must_not_hit"]:
            result["status"] = "通过"
        else:
            result["status"] = "未通过"
    elif groups:
        result["status"] = "未通过"
    else:
        result["status"] = "人工复核"

    # 人工复核标记：关键词过了，但问题有歧义或用户随后仍纠正
    if case.get("manual_review") and result["status"] == "通过":
        result["status"] = "人工复核"

    # 人已给最终判定：直接采用，不再让关键词翻案。
    verdict = str(case.get("manual_verdict") or "").strip()
    if verdict:
        result["status"] = verdict

    return result


def render_markdown(results: list[dict], generated: str) -> str:
    lines = [
        "# P35 基线报告（问答 golden set 50 条）",
        "",
        f"> 生成时间：{generated}",
        "> 方法：只读生产库，取历史回答做回溯评分；**本次不新调模型**。",
        "> 题库：`docs/golden/qa-golden-50.json`。",
        "> 注：P35.1 已补 `list_vocab`；题库里 `local-vocab` 的期望工具已更新。本报告保留 P35.0 的快照，便于前后对照。",
        "",
        "## 一、口径",
        "",
        "- 事实题：`fact_groups` 每组至少命中一个词；`must_not` 命中即失败。",
        "- 多轮：从第 1 轮数到第一次事实通过；超过 `max_turns` 即失败。",
        "- 本地数据：看历史 trace 是否用了期望工具；引用是否符合要求。",
        "- 合成题（无历史回答）：标「待在线评测」，不算进本次通过率。",
        "- 关键词只做初筛；歧义题必须人工复核。",
        "",
        "## 二、总览",
        "",
        "| 类别 | 通过 | 未通过 | 人工复核 | 能力缺口 | 待在线 | 合计 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    categories = []
    for item in results:
        if item["category"] not in categories:
            categories.append(item["category"])
    for category in categories:
        rows = [item for item in results if item["category"] == category]
        def count(status, rows=rows):
            return sum(1 for item in rows if item["status"] == status)
        lines.append(
            f"| {category} | {count('通过')} | {count('未通过')} | "
            f"{count('人工复核')} | {count('能力缺口')} | {count('待在线评测')} | {len(rows)} |")
    lines += [
        "",
        "## 三、逐条结果",
        "",
        "| 用例 | 类别 | 状态 | 首次通过轮 | 工具 | 引用 | 备注 |",
        "|---|---|---|---:|---|---|---|",
    ]
    for item in results:
        tools = "、".join(item["tools"]) or "—"
        citation = "—" if item["citation_ok"] is None else ("是" if item["citation_ok"] else "否")
        note = str(item["note"] or "").replace("|", "｜")[:80]
        lines.append(
            f"| {item['id']} | {item['category']} | {item['status']} | "
            f"{item['first_pass_turn'] or '—'} | {tools} | {citation} | {note} |")
    lines += [
        "",
        "## 四、主要发现",
        "",
        "1. **事实题**：`vector::emplace` 这类标准库事实是硬伤。正确事实是 `vector` 有 `emplace(pos, args...)`，第一个参数是位置迭代器；用户只传 `(char, int)` 所以编译失败。关键词初筛只能做初筛，歧义题要人工复核。",
        "2. **多轮纠错**：`multi-cpp-emplace` 的历史回答甚至把 `vector` 说成没有 `emplace`（事实错误）；`multi-rsync-locate` / `multi-siege-admin` 的首次通过轮分别是 4 / 3，说明「先确认指代 / 列已排除事实」缺失。",
        "3. **本地数据**：历史 trace 里工具使用率很低；合成题没有历史回答，需要在线评测补。",
        "4. **能力缺口已补**：P35.0 基线时 `local-vocab` 没有 `list_vocab`；P35.1 已补，当前题库期望工具已更新，改为待在线验证。",
        "",
        "## 五、限制",
        "",
        "- 历史回答来自不同版本（10-24 ~ 11-23），不是同一版 prompt 的受控运行；只能当「现状快照」。",
        "- `agent_runs.question` 只存前 200 字；超长代码题的工具匹配可能落空，标「—」不代表没跑。",
        "- 关键词初筛不能判断论证质量；歧义题已标「人工复核」。",
        "- 合成题（本地数据/部分英语题）没有历史回答，留到 P35.1 的在线 harness。",
        "",
        "## 六、下一步",
        "",
        "- P35.1 已完成：assistant 默认 11 个工具（9 核心 + 2 记忆），已补 `list_vocab`；在线试点见 `P35-在线试点-*.md`。",
        "- 在线 harness 需要：临时库快照、只读工具白名单、每题记录 trace/引用/轮数、人工复核入口。",
        "- 目标：事实题通过率不低于本次基线；多轮纠错 ≤2 轮；伪造引用 0。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P35.0 问答 golden set 回溯基线")
    parser.add_argument("--db", type=pathlib.Path,
                        default=pathlib.Path("D:/学习系统/learning.db"))
    args = parser.parse_args(argv)
    if not GOLDEN.is_file():
        print(f"找不到题库：{GOLDEN}")
        return 1
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = data.get("cases") or []
    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    try:
        results = [evaluate_case(conn, case) for case in cases]
    finally:
        conn.close()
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {"generated_at": generated, "db": str(args.db),
               "golden": str(GOLDEN.relative_to(ROOT)), "results": results}
    json_path = REPORT_DIR / f"baseline-{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    (REPORT_DIR / "latest-baseline.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MARKDOWN.write_text(render_markdown(results, generated), encoding="utf-8")
    counts = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print(f"已写 {json_path}")
    print(f"已写 {MARKDOWN}")
    print("状态：", " · ".join(f"{key} {value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
