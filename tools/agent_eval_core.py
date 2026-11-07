"""Agent 评测的核心口径：题库、离线段、在线判分、基线。

只放「怎么量」；命令行、报告渲染、临时目录在 `agent_eval.py`。
这样判分规则只有一份，脚本和测试都从这里导入。
"""
from __future__ import annotations

import json
import pathlib
import re
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUITE_PATH = ROOT / "docs" / "agent-eval-tasks.json"
BASELINE_PATH = ROOT / "docs" / "agent-eval-baseline.json"

# 离线段只允许只读工具：评测绝不能在真实数据上产生副作用。
READ_ONLY_TOOLS = {
    "search_records", "today_summary", "search_materials", "read_material",
    "search_dialog_archive", "recent_wrong_items", "due_reviews", "get_mastery",
    "get_train_summary", "list_recordings", "get_cet6_context",
    "life_cards", "life_items", "art_works", "read_attachment",
    "browser_status", "browser_history",
}

_FAIL_RE = re.compile(r"(失败[:：]|工具执行失败|没有这个工具)")
_EMPTY_RE = re.compile(r"(没有找到|还没有|暂无|没有记录|没有更多|一条也没有|0 条)")


def load_suite(path: pathlib.Path = SUITE_PATH) -> dict:
    with pathlib.Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    cases = data.get("cases") or []
    if not isinstance(cases, list) or not cases:
        raise SystemExit(f"题库为空或格式不对：{path}")
    ids = [str(case.get("id") or "") for case in cases]
    if any(not item for item in ids):
        raise SystemExit("题库里有用例缺少 id。")
    dup = {item for item in ids if ids.count(item) > 1}
    if dup:
        raise SystemExit(f"题库里有重复 id：{'、'.join(sorted(dup))}")
    return data


def is_empty(content: str, min_chars: int) -> bool:
    text = str(content or "").strip()
    if len(text) < max(1, min_chars):
        return True
    # 短句里出现「没有」基本就是空结果（"创作库里没有作品。""没有找到…"）；
    # 长回答里也可能有「没有」，所以加长度限制，避免把正常答句判成空。
    if len(text) < 60 and "没有" in text:
        return True
    return len(text) < 120 and bool(_EMPTY_RE.search(text))


def run_offline_case(case: dict, work: pathlib.Path) -> dict:
    """直接调用题目指定的读工具，验证能否从库里拿到内容。"""
    from learnsys.agent import tools

    spec = case.get("offline") or {}
    calls = spec.get("tools") or []
    min_chars = int(spec.get("min_chars") or 2)
    require_data = bool(spec.get("require_data"))
    ctx = tools.ToolContext(
        data_root=work,
        db_path=work / "learning.db",
        mode=str(case.get("mode") or "explain"),
    )
    started = time.monotonic()
    details: list[str] = []
    status = "通过"
    chars = 0
    for call in calls:
        name = str(call.get("name") or "")
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        if name not in READ_ONLY_TOOLS:
            details.append(f"{name} 不是只读工具，离线段拒绝执行")
            status = "失败"
            break
        try:
            content, preview, ok = tools.execute(name, args, ctx)
        except Exception as exc:  # noqa: BLE001 —— 评测要记录失败，不中断整套
            details.append(f"{name} 抛异常：{exc}")
            status = "失败"
            break
        content = str(content or "")
        chars += len(content)
        if not ok or _FAIL_RE.search(content):
            details.append(f"{name} 返回失败：{preview}")
            status = "失败"
        elif is_empty(content, min_chars):
            if require_data:
                details.append(f"{name} 没有返回数据（题目要求必须有）")
                status = "失败"
            elif status != "失败":
                status = "空数据"
                details.append(f"{name} 没有返回数据（可接受）")
    return {
        "id": str(case.get("id")),
        "domain": str(case.get("domain") or ""),
        "status": status,
        "ms": int((time.monotonic() - started) * 1000),
        "chars": chars,
        "details": details,
    }


def collect_live(case: dict, cfg) -> dict:
    """跑一轮真实 agent，收集判分需要的观察值。"""
    from learnsys.agent.loop import run
    from learnsys.agent.turn import AgentRequest

    used: list[str] = []
    errors: list[str] = []
    check_issues: list[str] = []
    confirms: list[str] = []
    done: dict = {}
    started = time.monotonic()
    request = AgentRequest(
        message=str(case.get("question") or ""),
        mode=str(case.get("mode") or "explain"),
        surface=str(case.get("surface") or "ask"),
        use_tools=True,
    )

    def deny(_request_id, name, _args):
        confirms.append(str(name))
        return False   # 评测一律不写学习数据

    for event in run(request, cfg=cfg, confirm=deny):
        if event.kind == "tool_start":
            used.append(str((event.data or {}).get("name") or ""))
        elif event.kind == "error":
            errors.append(event.text)
        elif event.kind == "check":
            check_issues = list((event.data or {}).get("issues") or [])
        elif event.kind == "done":
            done = dict(event.data or {})
    return {
        "id": str(case.get("id")),
        "domain": str(case.get("domain") or ""),
        "tools": [name for name in used if name],
        "confirms": confirms,
        "errors": errors,
        "check_issues": check_issues,
        "answer": str(done.get("text") or ""),
        "steps": int(done.get("steps") or 0),
        "tool_calls": int(done.get("tool_calls") or 0),
        "cost": float(done.get("cost") or 0.0),
        "ms": int((time.monotonic() - started) * 1000),
    }


def grade_live(case: dict, obs: dict) -> tuple[bool, list[str]]:
    """按题库里的规则判分；返回 (是否通过, 不通过原因)。"""
    spec = case.get("live") or {}
    reasons: list[str] = []
    used = set(obs.get("tools") or [])
    answer = str(obs.get("answer") or "")

    if obs.get("errors"):
        reasons.append("运行报错：" + "；".join(obs["errors"])[:200])
    if not answer.strip():
        reasons.append("没有返回正文")

    must_all = [str(name) for name in (spec.get("must_use_all") or [])]
    missing = [name for name in must_all if name not in used]
    if missing:
        reasons.append("缺少必需工具：" + "、".join(missing))

    must_any = [str(name) for name in (spec.get("must_use_any") or [])]
    if must_any and not (used & set(must_any)):
        reasons.append("没有使用任一预期工具：" + "、".join(must_any))

    forbidden = [str(name) for name in (spec.get("must_not_use") or [])]
    hit = [name for name in forbidden if name in used]
    if hit:
        reasons.append("用了不该用的工具：" + "、".join(hit))

    max_steps = int(spec.get("max_steps") or 0)
    if max_steps and obs.get("steps", 0) > max_steps:
        reasons.append(f"步骤 {obs['steps']} 超过上限 {max_steps}")

    max_tools = int(spec.get("max_tool_calls") or 0)
    if max_tools and obs.get("tool_calls", 0) > max_tools:
        reasons.append(f"工具调用 {obs['tool_calls']} 超过上限 {max_tools}")

    if spec.get("require_check_ok") and obs.get("check_issues"):
        reasons.append("引用自检未通过：" + "；".join(obs["check_issues"])[:200])

    need_any = [str(item) for item in (spec.get("answer_contains_any") or [])]
    if need_any and not any(item in answer for item in need_any):
        reasons.append("答案里没有出现预期说法：" + "、".join(need_any))

    forbidden_text = [str(item) for item in (spec.get("answer_not_contains") or [])]
    if forbidden_text:
        bad = [item for item in forbidden_text if item in answer]
        if bad:
            reasons.append("答案里出现了不该有的说法：" + "、".join(bad))

    min_chars = int(spec.get("min_answer_chars") or 20)
    if answer.strip() and len(answer.strip()) < min_chars:
        reasons.append(f"答案过短（{len(answer.strip())} 字）")

    return (not reasons), reasons


def baseline_entry(mode: str, result: dict) -> dict:
    if mode == "offline":
        return {"status": result["status"]}
    return {"pass": bool(result.get("pass")),
            "tools": list(result.get("tools") or []),
            "steps": int(result.get("steps") or 0),
            "tool_calls": int(result.get("tool_calls") or 0)}


def load_baseline() -> dict:
    try:
        with BASELINE_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_baseline(mode: str, results: list[dict]) -> str:
    import datetime as dt

    data = load_baseline()
    data["version"] = 1
    data[mode] = {item["id"]: baseline_entry(mode, item) for item in results}
    data[f"{mode}_saved_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    BASELINE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(BASELINE_PATH)


def compare(mode: str, results: list[dict]) -> list[str]:
    baseline = (load_baseline().get(mode) or {})
    if not baseline:
        return ["基线：无（运行 --save-baseline 建立）"]
    regressed, improved = [], []
    for result in results:
        old = baseline.get(result["id"])
        if not old:
            continue
        old_ok = (old.get("status") == "通过") if mode == "offline" else bool(old.get("pass"))
        new_ok = (result.get("status") == "通过") if mode == "offline" else bool(result.get("pass"))
        if old_ok and not new_ok:
            regressed.append(result["id"])
        elif not old_ok and new_ok:
            improved.append(result["id"])
    try:
        shown = BASELINE_PATH.relative_to(ROOT)
    except ValueError:            # 测试或自定义路径不在仓库里
        shown = BASELINE_PATH
    lines = [f"基线：{shown}（{len(baseline)} 条）"]
    if regressed:
        lines.append("退化：" + "、".join(regressed))
    if improved:
        lines.append("改进：" + "、".join(improved))
    if not regressed and not improved:
        lines.append("与基线一致")
    return lines
