"""六级精听接口：AI 分析（兼容旧的 /analyze）+ 断点同步 + 旧进度迁移。"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from learnsys import agent, store

router = APIRouter()

SYSTEM = "你是严谨、具体的英语听力教练。你只输出 JSON，不输出解释或 Markdown。"

PROMPT_HEAD = """下面是一个学生在某段英语听力里的断点记录。
每条包含：句子编号、他勾选的断点标签（生词/听不出/连读/句法/走神）、他自己写的原因、英文原句、循环回绕次数和总播放次数。
「循环回绕」是他主动把这一句反复回绕播放的次数，是难度信号：回绕多的句子通常更难；没有勾标签但反复循环的句子也要特别留意。不要只凭次数下结论，要结合标签和原话。
请做个性化分析，不要泛泛而谈：
1. summary：2–3 句话概括他当前最主要的听力障碍。
2. patterns：2–3 个问题模式；每个包含 name、evidence（引用他的原话、标签或循环次数）、advice（具体练法）。
3. priority：最该优先回听的 2–3 句；包含 sentence（句子编号）和 reason。
4. plan：3 条本周可执行的练习计划，每条不超过 2 句。
只输出 JSON：
{"summary":"...","patterns":[{"name":"...","evidence":"...","advice":"..."}],"priority":[{"sentence":3,"reason":"..."}],"plan":["...","..."]}

学生记录：
"""

PROMPT_PAPER = """下面是一个学生在**整卷**英语听力里记录的全部断点（跨 Section A/B/C）。
每条包含：所属 Section / 题型、句子编号、勾选的断点标签（生词/听不出/连读/句法/走神）、他自己写的原因、英文原句、循环回绕次数和总播放次数。
「循环回绕」是他主动把这一句反复回绕播放的次数，是难度信号：回绕多的句子通常更难；没有勾标签但反复循环的句子也要特别留意。不要只凭次数下结论，要结合标签和原话。
请做整卷级分析，按题型对比，不要泛泛而谈：
1. summary：3 句话概括他整卷最主要的听力障碍，并指出最弱的题型。
2. patterns：2–4 个跨段落反复出现的模式；每个包含 name、evidence（引用他的原话、标签或循环次数）、advice（具体练法）。
3. priority：最该优先回听的 3–5 句；包含 sentence（句子编号）和 reason。
4. plan：3 条本周可执行的练习计划，每条不超过 2 句。
只输出 JSON：
{"summary":"...","patterns":[{"name":"...","evidence":"...","advice":"..."}],"priority":[{"sentence":3,"reason":"..."}],"plan":["...","..."]}

学生记录：
"""


class AnalyzeRequest(BaseModel):
    paper: str = ""
    paper_id: str = ""
    section: str = ""
    item: str = ""
    scope: str = "item"
    sentences: list[dict] = Field(default_factory=list)


class Cet6Sentence(BaseModel):
    sentence: int = 0
    en: str = ""
    tags: list[str] = Field(default_factory=list)
    note: str = ""
    loops: int = 0
    plays: int = 0


class Cet6Sync(BaseModel):
    paper: str = ""
    paper_id: str = ""
    section: str = ""
    item: str = ""
    sentences: list[Cet6Sentence] = Field(default_factory=list)
    analysis: dict | None = None


class Cet6Import(BaseModel):
    items: dict[str, str] = Field(default_factory=dict)


def parse_json_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        return json.loads(text[i:j + 1])
    raise ValueError("模型输出里没有 JSON")


def _run_text(prompt: str) -> str:
    """让 Agent 用纯生成模式跑一段（不调工具、不用导师提示词）。"""
    text = ""
    error = ""
    for event in agent.run(agent.AgentRequest(
            prompt, system_override=SYSTEM, use_tools=False, mode="quick")):
        if event.kind == "done":
            text = str(event.data.get("text") or "")
        elif event.kind == "error":
            error = event.text
    if error:
        raise RuntimeError(error)
    if not text.strip():
        raise RuntimeError("模型没有返回文本")
    return text


def analyze(record: AnalyzeRequest) -> dict:
    rows = record.sentences or []
    if not rows:
        raise ValueError("没有可分析的记录")
    scope = record.scope
    limit = 120 if scope == "paper" else 80
    head = PROMPT_PAPER if scope == "paper" else PROMPT_HEAD
    lines = []
    for s in rows[:limit]:
        tags = "、".join(s.get("tags") or []) or "无"
        note = (s.get("note") or "").strip() or "无"
        en = (s.get("en") or "").strip()
        loops = int(s.get("loops") or 0)
        plays = int(s.get("plays") or 0)
        where = ""
        if s.get("section") or s.get("item"):
            where = f"{s.get('section', '')} / {s.get('item', '')} · "
        lines.append(
            f"{where}第 {s.get('sentence')} 句 | 标签：{tags} | 循环回绕：{loops} 次"
            f"（共播放 {plays} 次） | 我的原因：{note} | 英文：{en}")
    prompt = (head + f"\n材料：{record.paper} / {record.section} / {record.item}\n"
              + "\n".join(lines) + "\n\n只输出 JSON。")
    text = _run_text(prompt)
    obj = parse_json_text(text)
    return obj


@router.post("/analyze")
def analyze_compat(req: AnalyzeRequest):
    """旧工作台硬编码的地址：保持返回形状不变。"""
    try:
        result = analyze(req)
        from learnsys.agent.config import load_config
        return {"analysis": result, "model": load_config().model}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/cet6/analyze")
def analyze_v2(req: AnalyzeRequest):
    return analyze_compat(req)


@router.post("/api/cet6/sync")
def cet6_sync(req: Cet6Sync):
    """工作台分析完把断点送进学习系统时间线。失败不影响工作台。"""
    conn = store.connect()
    try:
        stamp = store.now()
        count = 0
        for item in req.sentences:
            tags = "、".join(item.tags or [])
            cur = conn.execute(
                "INSERT INTO cet6_events (ts, paper_id, paper_title, section, item, sentence, "
                "tags, note, loops, plays, analysis_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (stamp, req.paper_id, req.paper, req.section, req.item, item.sentence,
                 tags, item.note, item.loops, item.plays,
                 json.dumps(req.analysis, ensure_ascii=False) if req.analysis else ""))
            from learnsys.core import db as core_db
            core_db.index_row(
                conn, "cet6", int(cur.lastrowid), stamp,
                f"{req.paper} {req.section} {req.item} {item.en} {item.note} {tags}")
            count += 1
        conn.execute(
            "INSERT INTO events (ts, module, kind, ref_id, title, meta_json) "
            "VALUES (?, 'cet6', 'breakpoint', 0, ?, ?)",
            (stamp, f"{req.paper} / {req.section} / {req.item}",
             json.dumps({"count": count, "analysis": bool(req.analysis)},
                        ensure_ascii=False)))
        conn.commit()
        return {"ok": True, "count": count}
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/api/cet6/import")
def cet6_import(req: Cet6Import):
    """file:// 版工作台把 localStorage 快照送过来（P4 迁移桥用）。"""
    conn = store.connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cet6_imports "
            "(key TEXT PRIMARY KEY, value TEXT, ts TEXT)")
        stamp = store.now()
        for key, value in req.items.items():
            conn.execute(
                "INSERT INTO cet6_imports (key, value, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, ts = excluded.ts",
                (key, value, stamp))
        conn.commit()
        return {"ok": True, "count": len(req.items)}
    finally:
        conn.close()
