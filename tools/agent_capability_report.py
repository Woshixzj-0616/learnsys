"""Agent 能力体检（只读）：五个断面、一份可比基线。

对应 `docs/施工单/Agent-能力监控.md`。只读生产库与设置，不写学习数据；
`--save` 只写仓库里的基线 JSON。

用法：
    python tools/agent_capability_report.py
    python tools/agent_capability_report.py --days 7 --json
    python tools/agent_capability_report.py --save      # 更新基线
"""
from __future__ import annotations

import argparse
import inspect
import json
import pathlib
import sqlite3
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BASELINE = ROOT / "docs" / "agent-capability-baseline.json"

DOMAINS = {
    "知识点/BKT": ("get_mastery",),
    "复习队列": ("due_reviews",),
    "写作/翻译训练": ("get_train_summary",),
    "录像": ("list_recordings",),
    "资料库": ("search_materials", "read_material"),
    "六级精听": ("get_cet6_context",),
    "问答/转写": ("search_records", "today_summary"),
}
WEB_NAMES = ("web_search", "web_fetch", "fetch_url")


def _connect(db_path: pathlib.Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _count(conn, sql: str, *args) -> int:
    try:
        return int(conn.execute(sql, args).fetchone()[0] or 0)
    except sqlite3.Error:
        return 0


def _tools(mode: str = "explain", surface: str = "ask") -> dict:
    from learnsys.agent import tools
    schemas = tools.schemas_for(mode, surface=surface) or []
    names = [item["name"] for item in schemas]
    writes = sorted(set(names) & set(tools.CONFIRM_TOOLS))
    return {"names": names, "writes": writes,
            "confirm_count": len(writes)}


def _history_turns() -> int | None:
    try:
        from learnsys.server.routes_agent.common import _load_history
        return int(inspect.signature(_load_history).parameters["turns"].default)
    except Exception:
        return None


def collect(db_path: pathlib.Path, cfg=None, days: int = 7) -> dict:
    """汇总五个断面的当前状态。cfg 不传时按当前设置加载。"""
    if cfg is None:
        from learnsys.llm.config import load_config
        cfg = load_config()
    from learnsys import mcp_server
    tool_info = _tools("explain", "ask")
    names = set(tool_info["names"])
    data = {
        "generated_at": "",
        "db": str(db_path),
        "days": int(days),
        "perception": {
            "vision_ready": bool(getattr(cfg, "vision_ready", False)),
            "vision_model": getattr(cfg, "vision_model", "") if getattr(
                cfg, "vision_ready", False) else "",
            "web_tools": sorted(name for name in WEB_NAMES if name in names),
            "materials": 0,
            "recordings": 0,
        },
        "tools": {
            "total": len(names),
            "surface_quickbar": len(_tools("explain", "quickbar")["names"]),
            "surface_cet6": len(_tools("explain", "cet6")["names"]),
            "surface_quick": len(_tools("quick", "ask")["names"]),
            "writes": tool_info["writes"],
            "domains": {name: any(tool in names for tool in needed)
                        for name, needed in DOMAINS.items()},
            "mcp_tools": len(getattr(mcp_server, "TOOLS", {})),
            "mcp_read_only": sum(1 for item in getattr(mcp_server, "TOOLS", {}).values()
                                 if item.get("read_only")),
        },
        "memory": {
            "memories_active": 0,
            "memories_total": 0,
            "conversations": 0,
            "conversation_summaries": 0,
            "asks": 0,
            "history_turns": _history_turns(),
        },
        "reliability": {
            "auto_route": str(getattr(cfg, "auto_route", "") or "off"),
            "strong_model": str(getattr(cfg, "strong_model", "") or ""),
            "runs": 0,
            "runs_with_tools": 0,
            "errors": 0,
            "check_ok": 0,
            "check_failed": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_read_tokens": 0,
            "calls_by_model": {},
            "calls_by_source": {},
            "tool_calls": {},
            "tool_failures": {},
        },
        "proactivity": {
            "write_tools": len(tool_info["writes"]),
            "deep_available": False,
            "deep_calls": 0,
            "vision_calls": 0,
        },
    }
    if not db_path.is_file():
        return data
    conn = _connect(db_path)
    try:
        p = data["perception"]
        p["materials"] = _count(conn, "SELECT COUNT(*) FROM materials")
        p["recordings"] = _count(
            conn, "SELECT COUNT(*) FROM sessions WHERE video_path <> ''")
        m = data["memory"]
        m["memories_active"] = _count(
            conn, "SELECT COUNT(*) FROM agent_memories WHERE status = 'active'")
        m["memories_total"] = _count(conn, "SELECT COUNT(*) FROM agent_memories")
        m["conversations"] = _count(conn, "SELECT COUNT(*) FROM conversations")
        m["conversation_summaries"] = _count(
            conn, "SELECT COUNT(*) FROM conversations "
                  "WHERE summary IS NOT NULL AND summary <> ''")
        m["asks"] = _count(conn, "SELECT COUNT(*) FROM asks")
        r = data["reliability"]
        since = f"-{max(1, int(days))} days"
        r["runs"] = _count(conn, "SELECT COUNT(*) FROM agent_runs "
                                 "WHERE started_at >= date('now', ?)", since)
        r["runs_with_tools"] = _count(conn, "SELECT COUNT(*) FROM agent_runs "
                                           "WHERE tool_count > 0 AND started_at >= date('now', ?)", since)
        r["errors"] = _count(conn, "SELECT COUNT(*) FROM agent_runs "
                                   "WHERE error <> '' AND started_at >= date('now', ?)", since)
        r["check_ok"] = _count(conn, "SELECT COUNT(*) FROM agent_runs "
                                     "WHERE check_ok = 1 AND started_at >= date('now', ?)", since)
        r["check_failed"] = _count(conn, "SELECT COUNT(*) FROM agent_runs "
                                         "WHERE check_ok = 0 AND started_at >= date('now', ?)", since)
        for row in conn.execute(
                "SELECT model, COUNT(*) n FROM model_usage WHERE day >= date('now', ?) "
                "GROUP BY model", (since,)):
            r["calls_by_model"][row[0] or ""] = int(row[1])
        for row in conn.execute(
                "SELECT source, COUNT(*) n FROM model_usage WHERE day >= date('now', ?) "
                "GROUP BY source", (since,)):
            r["calls_by_source"][row[0] or ""] = int(row[1])
        row = conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), "
            "COALESCE(SUM(cache_read_tokens),0) FROM model_usage WHERE day >= date('now', ?)",
            (since,)).fetchone()
        r["prompt_tokens"], r["completion_tokens"], r["cache_read_tokens"] = (
            int(row[0] or 0), int(row[1] or 0), int(row[2] or 0))
        calls = Counter()
        failures = Counter()
        for row in conn.execute(
                "SELECT trace_json FROM agent_runs WHERE started_at >= date('now', ?)",
                (since,)):
            try:
                trace = json.loads(row[0] or "[]")
            except (TypeError, ValueError):
                continue
            for event in trace if isinstance(trace, list) else []:
                if not isinstance(event, dict):
                    continue
                kind = event.get("kind")
                payload = event.get("data") or {}
                name = str(payload.get("name") or payload.get("tool") or "")
                if not name:
                    continue
                if kind == "tool_start":
                    calls[name] += 1
                elif kind == "tool_end" and payload.get("ok") is False:
                    failures[name] += 1
        r["tool_calls"] = dict(calls.most_common())
        r["tool_failures"] = dict(failures.most_common())
        pro = data["proactivity"]
        pro["deep_calls"] = r["calls_by_source"].get("deep", 0)
        pro["vision_calls"] = r["calls_by_source"].get("vision", 0)
    finally:
        conn.close()
    try:
        from learnsys.agent import deep
        data["proactivity"]["deep_available"] = bool(deep.available())
    except Exception:
        pass
    return data


def render(data: dict) -> str:
    p, t, m = data["perception"], data["tools"], data["memory"]
    r, pro = data["reliability"], data["proactivity"]
    covered = sum(1 for value in t["domains"].values() if value)
    lines = [f"Agent 能力体检 · 近 {data['days']} 天 · {data['db']}", ""]
    lines.append("【感知面】")
    lines.append(f"- 视觉模型：{'已启用 ' + p['vision_model'] if p['vision_ready'] else '未启用（只有 OCR）'}")
    lines.append(f"- 联网工具：{'、'.join(p['web_tools']) if p['web_tools'] else '无'}")
    lines.append(f"- 资料 {p['materials']} 份 ｜ 录像 {p['recordings']} 段")
    lines.append("")
    lines.append("【工具面】")
    lines.append(f"- 工具总数 {t['total']}（工作台）｜ 快捷栏 {t['surface_quickbar']} ｜ "
                 f"六级 {t['surface_cet6']} ｜ 速答 {t['surface_quick']}")
    lines.append(f"- 需要确认的副作用工具：{len(t['writes'])} 个"
                 f"（{'、'.join(t['writes'])}）")
    lines.append(f"- 数据域覆盖：{covered}/{len(t['domains'])} —— "
                 + "；".join(f"{name}{'✓' if ok else '✗'}"
                             for name, ok in t["domains"].items()))
    lines.append(f"- MCP：{t['mcp_tools']} 个工具，"
                 f"{t['mcp_read_only']} 个标记只读"
                 + ("（其余只写翻译缓存）" if t["mcp_read_only"] < t["mcp_tools"] else ""))
    lines.append("")
    lines.append("【记忆面】")
    lines.append(f"- 长期记忆 {m['memories_active']} 条启用 / {m['memories_total']} 条总计")
    lines.append(f"- 会话 {m['conversations']} 个，有摘要 {m['conversation_summaries']} 个")
    lines.append(f"- 历史带入窗口：最近 {m['history_turns']} 轮"
                 if m["history_turns"] is not None else "- 历史带入窗口：未知")
    lines.append("")
    lines.append("【可靠性与成本】")
    lines.append(f"- 路由：{r['auto_route']}，强模型 {r['strong_model'] or '未设置'}")
    lines.append(f"- 运行 {r['runs']} 次，其中用工具 {r['runs_with_tools']} 次；错误 {r['errors']} 次")
    lines.append(f"- 自检：通过 {r['check_ok']} / 未通过 {r['check_failed']}")
    hit = (r["cache_read_tokens"] / r["prompt_tokens"] * 100.0
           if r["prompt_tokens"] else 0.0)
    lines.append(f"- tokens：prompt {r['prompt_tokens']}，completion {r['completion_tokens']}，"
                 f"缓存命中 {hit:.0f}%")
    lines.append(f"- 模型调用：{r['calls_by_model'] or '无'}；来源：{r['calls_by_source'] or '无'}")
    lines.append(f"- 工具调用：{r['tool_calls'] or '无'}")
    lines.append("")
    lines.append("【主动性与互操作】")
    lines.append(f"- 写工具 {pro['write_tools']} 个；深度分析"
                 f"{'已启用' if pro['deep_available'] else '未启用'}（近 {data['days']} 天 {pro['deep_calls']} 次）")
    lines.append(f"- 看图调用：近 {data['days']} 天 {pro['vision_calls']} 次")
    lines.append("")
    missing = [name for name, ok in t["domains"].items() if not ok]
    if missing:
        lines.append("结论：仍缺数据域工具 —— " + "、".join(missing) + "。")
    else:
        lines.append("结论：七个学习数据域都有读工具；下一步看真实使用与写入闭环。")
    if not p["vision_ready"]:
        lines.append("提醒：视觉未启用，截图题只剩 OCR。")
    if not p["web_tools"]:
        lines.append("提醒：没有联网工具，时效性问题只能回答“不确定”。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 能力体检（只读）")
    parser.add_argument("--db", default="", help="learning.db 路径；默认按数据目录")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--save", action="store_true",
                        help=f"把当前结果写成基线：{BASELINE.relative_to(ROOT)}")
    args = parser.parse_args()

    if args.db:
        db_path = pathlib.Path(args.db)
    else:
        from learnsys import config
        db_path = config.db_path()
    data = collect(db_path, days=args.days)
    if args.save:
        data["generated_at"] = __import__("datetime").datetime.now().isoformat(
            timespec="seconds")
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(f"基线已写入：{BASELINE.relative_to(ROOT)}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
