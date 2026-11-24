"""P35.1 问答 golden set 在线试点（会消耗模型调用）。

用法：
    python tools/qa_golden_live.py --pilot
    python tools/qa_golden_live.py --case multi-cpp-emplace --case local-vocab
    python tools/qa_golden_live.py --all

安全边界：
- 生产库先快照到临时目录，agent 的读写都在临时库；
- 写工具一律拒绝（confirm 回调返回 False），run_code 只在临时沙箱跑；
- 临时库的每日调用上限由本脚本设置，避免一次试点花掉整天额度。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
import sqlite3
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learnsys import store
from learnsys.agent import debug_intent, loop
from learnsys.agent import tools as agent_tools
from learnsys.agent.selfcheck import Evidence, cited_web_dates, urls_in
from learnsys.agent.turn import AgentRequest
from learnsys.llm.config import load_config
from learnsys.services import home as home_service
from tools.qa_golden_report import check_citation, check_fact

GOLDEN = ROOT / "docs" / "golden" / "qa-golden-50.json"
REPORT_DIR = ROOT / "eval" / "qa"

PILOT = [
    "multi-cpp-emplace",
    "multi-rsync-locate",
    "multi-siege-admin",
    "multi-quicksearch-key",
    "local-vocab",
    "local-materials-tcp",
    "local-wrong-items",
    "english-fireworks",
    "code-prefix-expr",
    "fact-net-tcp-handshake",
]

def snapshot_db(source: pathlib.Path, target: pathlib.Path) -> None:
    if not source.is_file():
        store.connect(target).close()
        return
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def ask_question(conn: sqlite3.Connection, ask_id: int) -> str:
    row = conn.execute("select question from asks where id=?", (ask_id,)).fetchone()
    return str(row[0]) if row else ""


_ASK_COLS = ("question", "answer", "conversation_id", "thread", "kind",
             "image_path")


def _ask_row(conn: sqlite3.Connection, ask_id: int) -> dict:
    row = conn.execute(
        f"select {', '.join(_ASK_COLS)} from asks where id=?",
        (int(ask_id),)).fetchone()
    if not row:
        return {}
    return dict(zip(_ASK_COLS, row))


def _thread_pairs(conn: sqlite3.Connection, thread, ask_id: int
                  ) -> list[tuple[str, str]]:
    """同一 thread 里、受测提问之前的问答对（ask 行没写 conversation_id 时用）。"""
    anchor = conn.execute("select ts from asks where id=?", (int(ask_id),)).fetchone()
    if not anchor:
        return []
    rows = conn.execute(
        "select question, answer from asks where thread=?"
        " and (ts < ? or (ts = ? and id < ?)) order by ts, id",
        (str(thread), anchor[0], anchor[0], int(ask_id))).fetchall()
    return [(str(question or ""), str(answer or ""))
            for question, answer in rows
            if str(question or "").strip() and str(answer or "").strip()]


def case_history(conn: sqlite3.Connection, case: dict) -> list[tuple[str, str]]:
    """从原会话回放第一句受测问题之前的前文。

    多轮用例常是「对话中段」的切片（例如「那怎么定位错误」）；冷启动会人为
    制造歧义，测不出模型在真实上下文里的收敛速度。只回放前文，不计入受测轮次。

    会话来源优先 `case.conversation_id`；老用例只记了 `source_ask_ids`，
    就从 ask 行补 `conversation_id`，再退回同一 thread 的问答对。
    """
    conversation_id = int(case.get("conversation_id") or 0)
    turns = case.get("turns") or []
    ids = case.get("source_ask_ids") or []
    first_row = _ask_row(conn, ids[0]) if ids else {}
    if first_row and not conversation_id:
        conversation_id = int(first_row.get("conversation_id") or 0)
    if not conversation_id:
        # 没有会话记录：同 thread 的旧问答就是当时的前文。
        if ids and first_row.get("thread"):
            return _thread_pairs(conn, first_row["thread"], ids[0])
        return []
    first = " ".join(str(turns[0]).split()) if turns else ""
    if not first:
        first = " ".join(str(case.get("question") or "").split())
    if not first and first_row:
        first = " ".join(str(first_row.get("question") or "").split())
    if not first:
        return []
    try:
        pairs = store.conversation_pairs(conn, conversation_id)
    except Exception:
        return []
    for index, (question, _answer) in enumerate(pairs):
        if " ".join(str(question).split()) == first:
            return pairs[:index]
    return []


def case_skip_reason(conn: sqlite3.Connection, case: dict) -> str:
    """图片提问且没有可用文字题干时，离线 harness 不带图，不能算模型答错。

    截图类提问常常同时存了 OCR 文本（例如「为什么分块查找…」）；那种情况
    仍可当文字题跑。只有题干/公式确实只在截图里的才跳过——
    显式标 `needs_image` 的用例优先按这条处理。
    """
    if case.get("needs_image"):
        return "题干或公式只在截图里（needs_image），离线 harness 不带图"
    ids = case.get("source_ask_ids") or []
    if not ids:
        return ""
    row = _ask_row(conn, ids[0])
    question = " ".join(str(row.get("question") or "").split())
    if (row.get("kind") == "image" and row.get("image_path")
            and len(question) < 8):
        return "图片题：题干只在截图里（文字过短），离线 harness 不带图，无法复现"
    return ""


def skipped_result(case: dict, reason: str) -> dict:
    return {
        "id": case["id"],
        "category": case["category"],
        "question": case.get("question") or "",
        "turns_run": 0,
        "score": {
            "status": "跳过", "first_pass_turn": None, "must_not_hit": False,
            "tools": [], "tools_ok": None, "citation_ok": None,
            "fake_urls": [], "fake_dates": [],
            "turn_facts": [], "model_calls": 0, "cost": 0.0, "reason": reason,
        },
        "turns": [],
        "work_root": "",
    }


def case_questions(conn: sqlite3.Connection, case: dict) -> list[str]:
    """优先用真实 asks 原文；代码题只跑第一问；其余用 turns / question。"""
    ids = case.get("source_ask_ids") or []
    if case.get("category") == "代码调试" and ids:
        question = ask_question(conn, int(ids[0]))
        if question:
            return [question]
    if ids:
        questions = [ask_question(conn, int(item)) for item in ids]
        if all(questions):
            return questions
    turns = case.get("turns") or []
    if turns:
        return [str(item) for item in turns]
    return [str(case.get("question") or "")]


def run_turn(cfg, question: str, history: list[tuple[str, str]],
             personal_state: str) -> dict:
    debug = debug_intent.detect(question)
    request = AgentRequest(
        message=question,
        history=list(history),
        personal_state=personal_state,
        mode="explain",
        surface="ask",
        profile="assistant",
        use_tools=True,
        auto_run_code=bool(debug["code_debug"] or debug["run_requested"]),
    )
    tools: list[str] = []
    errors: list[str] = []
    done: dict = {}
    route: dict = {}
    started = time.monotonic()

    def deny(_request_id, _name, _args):
        return False

    # 包一层 tools.execute，留下本轮工具原文：伪造链接 / 伪造读取日期
    # 只能拿本轮证据来核对（done 事件里没有工具正文）。
    captured: list[tuple[str, dict, str]] = []
    original_execute = agent_tools.execute

    def _capture(name, raw_input, ctx):
        raw, preview, ok = original_execute(name, raw_input, ctx)
        captured.append((str(name), dict(raw_input or {}), str(raw or "")))
        return raw, preview, ok

    agent_tools.execute = _capture
    try:
        for event in loop.run(request, cfg=cfg, confirm=deny):
            if event.kind == "tool_start":
                name = str((event.data or {}).get("name") or "")
                if name:
                    tools.append(name)
            elif event.kind == "error":
                errors.append(event.text)
            elif event.kind == "route":
                route = dict(event.data or {})
            elif event.kind == "done":
                done = dict(event.data or {})
    finally:
        agent_tools.execute = original_execute

    evidence = Evidence()
    for name, args, content in captured:
        evidence.add(name, args, content)
    answer = str(done.get("text") or "")
    known_urls = evidence.urls() | urls_in(question)
    fake_urls = sorted(url for url in urls_in(answer) if url not in known_urls)
    fake_dates = sorted(date for date in cited_web_dates(answer)
                        if date not in evidence.web_dates)
    return {
        "question": question[:200],
        "answer": answer,
        "tools": tools,
        "errors": errors,
        "route": route,
        "model": str(route.get("model") or ""),
        "steps": int(done.get("steps") or 0),
        "model_calls": int(done.get("model_calls") or 0),
        "tool_calls": int(done.get("tool_calls") or 0),
        "cost": float(done.get("cost") or 0.0),
        "ms": int((time.monotonic() - started) * 1000),
        "prompt": done.get("prompt") or {},
        "evidence_urls": sorted(evidence.urls()),
        "web_dates": sorted(evidence.web_dates),
        "fake_urls": fake_urls,
        "fake_dates": fake_dates,
    }


def score_case(case: dict, turns: list[dict]) -> dict:
    expected = case.get("expected") or {}
    groups = expected.get("fact_groups") or []
    must_not = expected.get("must_not") or []
    tools_any = expected.get("tools_any") or []
    citation = str(expected.get("citation") or "none")
    max_turns = int(expected.get("max_turns") or 1)

    first_pass = None
    must_hit = False
    turn_facts = []
    for index, turn in enumerate(turns, 1):
        ok, bad = check_fact(turn["answer"], groups, must_not) if groups else (False, False)
        turn_facts.append({"turn": index, "fact_ok": ok, "must_not": bad})
        if ok and not bad and first_pass is None:
            first_pass = index
        if bad:
            must_hit = True
    used = []
    for turn in turns:
        for name in turn["tools"]:
            if name not in used:
                used.append(name)
    last = turns[-1]["answer"] if turns else ""
    citation_ok = check_citation(last, citation) if citation != "none" else None
    tools_ok = any(name in used for name in tools_any) if tools_any else None
    fake_urls = sorted({url for turn in turns for url in turn.get("fake_urls") or []})
    fake_dates = sorted({date for turn in turns for date in turn.get("fake_dates") or []})
    citation_clean = not fake_urls and not fake_dates

    if ((groups and first_pass is not None and first_pass <= max_turns and not must_hit)
            or (tools_any and tools_ok and (citation_ok is not False))) \
            and citation_clean:
        status = "通过"
    elif case.get("manual_review"):
        status = "人工复核"
    else:
        status = "未通过"
    if case.get("manual_review") and status == "通过":
        status = "人工复核"
    return {
        "status": status,
        "first_pass_turn": first_pass,
        "must_not_hit": must_hit,
        "tools": used,
        "tools_ok": tools_ok,
        "citation_ok": citation_ok,
        "fake_urls": fake_urls,
        "fake_dates": fake_dates,
        "turn_facts": turn_facts,
        "model_calls": sum(turn["model_calls"] for turn in turns),
        "cost": sum(turn["cost"] for turn in turns),
    }


def run_case(conn, cfg, case: dict, work_root: pathlib.Path) -> dict:
    questions = case_questions(conn, case)
    history = case_history(conn, case)
    turns = []
    for question in questions:
        # 每轮按当轮问题生成学习状态：无关的英语卡点不能带进 rsync/C++ 题。
        try:
            personal_state = home_service.agent_state(
                conn, scope="learning", query=question)
        except Exception as exc:  # noqa: BLE001 —— 试点不因个人状态失败中断
            print(f"个人状态读取失败：{exc}", file=sys.stderr)
            personal_state = ""
        obs = run_turn(cfg, question, history, personal_state)
        turns.append(obs)
        if obs["answer"].strip():
            history.append((question, obs["answer"]))
        if obs["errors"]:
            break
    score = score_case(case, turns)
    return {
        "id": case["id"],
        "category": case["category"],
        "question": case.get("question") or "",
        "turns_run": len(turns),
        "score": score,
        "turns": turns,
        "work_root": str(work_root),
    }


def render(results: list[dict], generated: str, cfg) -> str:
    lines = [
        "# P35.2 在线试点（问答 golden set）",
        "",
        f"> 生成时间：{generated}",
        f"> 模型：{cfg.model}（fast={cfg.fast_model}，speed={cfg.speed}，auto_route={cfg.auto_route}）",
        f"> 临时库每日上限：{cfg.daily_call_limit} 次",
        "> 多轮用例：有 `conversation_id` 的会先回放第一句受测问题之前的原会话前文，再把 `turns` 作为受测轮次。",
        "",
        "| 用例 | 类别 | 结果 | 轮数 | 首次通过 | 工具 | 引用 | 伪造 | 调用 | 花费 |",
        "|---|---|---|---:|---:|---|---|---|---:|---:|",
    ]
    for item in results:
        score = item["score"]
        citation = "—" if score["citation_ok"] is None else ("是" if score["citation_ok"] else "否")
        fake = []
        if score.get("fake_urls"):
            fake.append(f"链接 {len(score['fake_urls'])} 个")
        if score.get("fake_dates"):
            fake.append(f"日期 {len(score['fake_dates'])} 个")
        lines.append(
            f"| {item['id']} | {item['category']} | {score['status']} | "
            f"{item['turns_run']} | {score['first_pass_turn'] or '—'} | "
            f"{'、'.join(score['tools']) or '—'} | {citation} | "
            f"{'、'.join(fake) or '0'} | "
            f"{score['model_calls']} | {score['cost']:.4f} |")
    lines += ["", "## 逐条回答（前 400 字）", ""]
    for item in results:
        lines.append(f"### {item['id']} · {item['score']['status']}")
        if item["score"].get("reason"):
            lines.append(f"- **跳过原因**：{item['score']['reason']}")
        for url in item["score"].get("fake_urls") or []:
            lines.append(f"- **伪造链接**：{url}")
        for date in item["score"].get("fake_dates") or []:
            lines.append(f"- **伪造日期**：{date}")
        for turn in item["turns"]:
            answer = " ".join(str(turn["answer"]).split())[:400]
            lines.append(f"- **问**：{turn['question']}")
            lines.append(f"  **答**：{answer}")
            if turn["tools"]:
                lines.append(f"  **工具**：{'、'.join(turn['tools'])}")
            if turn["errors"]:
                lines.append(f"  **错误**：{'；'.join(turn['errors'])}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P35.1 问答 golden set 在线试点")
    parser.add_argument("--case", action="append", default=None)
    parser.add_argument("--pilot", action="store_true", help="跑内置 10 条试点")
    parser.add_argument("--all", action="store_true", help="跑全部 50 条")
    parser.add_argument("--db", type=pathlib.Path,
                        default=pathlib.Path("D:/学习系统/learning.db"))
    parser.add_argument("--call-limit", type=int, default=40,
                        help="临时库的每日调用上限，默认 40")
    args = parser.parse_args(argv)

    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = data.get("cases") or []
    if args.case:
        wanted = set(args.case)
        cases = [case for case in cases if case["id"] in wanted]
    elif args.pilot:
        wanted = set(PILOT)
        cases = [case for case in cases if case["id"] in wanted]
    elif not args.all:
        parser.error("请指定 --pilot / --case / --all")
    if not cases:
        print("没有匹配的用例")
        return 1

    base = load_config()
    with tempfile.TemporaryDirectory(prefix="learnsys-qa-") as tmp:
        root = pathlib.Path(tmp)
        target_db = root / "learning.db"
        snapshot_db(args.db, target_db)
        cfg = dataclasses.replace(
            base, data_root=root, profile_path=root / "学习档案.md",
            daily_call_limit=max(1, int(args.call_limit)), daily_cost_limit=0.0)
        conn = store.connect(target_db)
        try:
            results = []
            for index, case in enumerate(cases, 1):
                print(f"[{index}/{len(cases)}] {case['id']} ...", flush=True)
                reason = case_skip_reason(conn, case)
                if reason:
                    print(f"  -> 跳过 · {reason}", flush=True)
                    results.append(skipped_result(case, reason))
                    continue
                result = run_case(conn, cfg, case, root)
                results.append(result)
                score = result["score"]
                print(f"  -> {score['status']} · 轮 {result['turns_run']} · "
                      f"首次 {score['first_pass_turn']} · 工具 {score['tools']} · "
                      f"调用 {score['model_calls']} · {score['cost']:.4f}", flush=True)
                if score["model_calls"] == 0 and any(turn["errors"] for turn in result["turns"]):
                    print("  -> 这条首轮就报错，继续下一条", flush=True)
        finally:
            conn.close()

    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {"generated_at": generated, "model": cfg.model,
               "call_limit": cfg.daily_call_limit, "results": results}
    json_path = REPORT_DIR / f"live-pilot-{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    md_path = ROOT / "docs" / "施工单" / f"P35-在线试点-{stamp}.md"
    md_path.write_text(render(results, generated, cfg), encoding="utf-8")
    print(f"已写 {json_path}")
    print(f"已写 {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
