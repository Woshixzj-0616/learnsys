"""从封存的对话总汇里抽取「跨会话有效」的个人事实。

三道闸门：
1. `evidence` 必须是本批提供的锚点；
2. `quote` 必须是该锚点消息的原文子串；
3. 置信度 >= 0.75 才进 active，否则进 candidate。

模型只读，不写库；写库由本模块统一走 store.add_memory。
"""
from __future__ import annotations

import dataclasses
import hashlib
import re

from learnsys import store
from learnsys.agent import budget
from learnsys.agent import usage as agent_usage
from learnsys.core import jsontext
from learnsys.llm import provider_anthropic
from learnsys.llm.config import load_config
from learnsys.store import memory_batches

from .parse import iter_archive_messages

SIGNALS = ("以后", "每次", "默认", "记住", "我习惯", "不要", "别", "我喜欢",
           "我是", "我在学", "目标", "考试", "项目", "讨厌", "偏好", "计划")
KINDS = ("preference", "rule", "identity", "goal", "constraint", "project")
MAX_CHUNK_CHARS = 10_000
MAX_FACTS_PER_CHUNK = 8
ACTIVE_CONFIDENCE = 0.75

# 严格口径：只保留用户亲口说出长期偏好的块。
STRICT_TERMS = ("我习惯", "我希望", "我喜欢", "我以后", "每次", "以后都",
                "不要", "别", "记住", "我在学", "我的目标", "我是", "我要")
# 项目类话题不进学习画像；它们属于对应项目自己的记忆。
PROJECT_TERMS = ("旅行", "travel", "金融", "股票", "仓库", "部署", "发版",
                 "智能旅行", "agent 项目")

SYSTEM = """你是「学习工作台」的记忆整理器。读对话摘录，只输出一个 JSON 对象：
{"facts":[{"content":"...","kind":"preference|rule|identity|goal|constraint|project",
"scope":"global|course:...|exam:cet6|project:...","confidence":0.0,
"evidence":"<给出的锚点>","quote":"原文片段"}]}

只收用户**明确表达、跨会话有效**的偏好、规矩、身份、目标或约束；
不收一次任务细节、临时安排、第三方隐私、密钥/密码；不要编造；
每条 content 是一句完整的话，最多 200 字；没有就 {"facts":[]}。
evidence 必须原样使用下面给出的锚点，quote 必须是该条消息里的原文片段。"""

def chunk_messages(messages: list[dict], max_chars: int = MAX_CHUNK_CHARS) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for message in messages:
        length = len(message["text"])
        if current and size + length > max_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(message)
        size += length
    if current:
        chunks.append(current)
    return chunks


def _chunk_key(chunk: list[dict]) -> str:
    raw = "|".join([chunk[0]["anchor"], chunk[-1]["anchor"],
                    str(len(chunk))])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _wanted(chunk: list[dict]) -> bool:
    text = "\n".join(message["text"] for message in chunk)
    return any(signal in text for signal in SIGNALS)


def _user_text(chunk: list[dict]) -> str:
    return "\n".join(message["text"] for message in chunk
                     if message["role"] == "用户")


def _strict(chunk: list[dict]) -> bool:
    text = _user_text(chunk)
    return any(term in text for term in STRICT_TERMS)


def _project(chunk: list[dict]) -> bool:
    text = _user_text(chunk).lower()
    return any(term.lower() in text for term in PROJECT_TERMS)


def _prompt(chunk: list[dict]) -> str:
    lines = []
    for message in chunk:
        lines.append(f"锚点：{message['anchor']}\n"
                     f"角色：{message['role']}\n"
                     f"内容：{message['text']}")
    return "【对话摘录】\n\n" + "\n\n".join(lines)


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "").lower())


def _validate(fact: dict, chunk: list[dict]) -> dict | None:
    by_anchor = {message["anchor"]: message["text"] for message in chunk}
    anchor = str(fact.get("evidence") or "").strip()
    if anchor not in by_anchor:
        return None
    content = " ".join(str(fact.get("content") or "").split())[:500]
    if len(content) < 6:
        return None
    quote = str(fact.get("quote") or "")
    if quote and _normalize(quote) not in _normalize(by_anchor[anchor]):
        return None
    kind = str(fact.get("kind") or "preference")
    if kind not in KINDS:
        kind = "preference"
    scope = str(fact.get("scope") or "global")
    if not (scope == "global" or scope.startswith(
            ("course:", "exam:", "project:"))):
        scope = "global"
    try:
        confidence = max(0.0, min(float(fact.get("confidence") or 0.6), 1.0))
    except (TypeError, ValueError):
        confidence = 0.6
    return {"content": content, "kind": kind, "scope": scope,
            "confidence": confidence, "evidence": anchor,
            "quote": quote[:200]}


def _call_model(cfg, prompt: str, data_root) -> str:
    fast = dataclasses.replace(
        cfg, model=cfg.fast_model or cfg.model, thinking=False,
        max_tokens=min(int(cfg.max_tokens or 900), 900), speed="fast")
    parts: list[str] = []
    result = None
    for event in provider_anthropic.stream_messages(
            fast, SYSTEM,
            [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            None, timeout=90.0):
        if event.kind == "text":
            parts.append(event.text)
        elif event.kind == "done":
            result = event.result
    if result is not None and getattr(result, "usage", None):
        agent_usage.record(data_root, source="archive_extract",
                           model=fast.model, usage=result.usage, cfg=fast)
    return (result.text if result is not None and result.text
            else "".join(parts)).strip()


def extract_archive(conn, archive_path, *, batch_id: int = 0,
                    max_calls: int = 150, dry_run: bool = False,
                    data_root=None, strict: bool = False,
                    exclude_projects: bool = False,
                    candidate_only: bool = False) -> dict:
    messages = iter_archive_messages(archive_path)
    chunks = [chunk for chunk in chunk_messages(messages) if _wanted(chunk)]
    if strict:
        chunks = [chunk for chunk in chunks if _strict(chunk)]
    if exclude_projects:
        chunks = [chunk for chunk in chunks if not _project(chunk)]
    chunks.reverse()                       # 先抽最近会话
    done = memory_batches.done_chunk_keys(conn)
    pending = [chunk for chunk in chunks if _chunk_key(chunk) not in done]
    planned = pending[:max(max_calls, 0)]
    if dry_run:
        return {"messages": len(messages), "chunks": len(chunks),
                "planned": len(planned), "calls": 0, "facts": 0}
    cfg = load_config()
    if not cfg.ready:
        return {"ok": False, "reason": "模型未配置", "planned": len(planned)}
    added = merged = failed = calls = 0
    for chunk in planned:
        key = _chunk_key(chunk)
        memory_batches.add_chunk(conn, batch_id, key,
                                 source=chunk[0]["anchor"].split("/")[1],
                                 session_ids=chunk[0]["anchor"])
        if budget.check(cfg):
            break
        try:
            text = _call_model(cfg, _prompt(chunk), data_root or cfg.data_root)
            payload = jsontext.parse_object(text)
            calls += 1
            facts = payload.get("facts") or []
        except Exception as exc:  # noqa: BLE001
            failed += 1
            memory_batches.update_chunk(conn, key, status="failed",
                                        error=str(exc)[:300])
            continue
        kept = []
        for fact in facts[:MAX_FACTS_PER_CHUNK]:
            clean = _validate(fact, chunk)
            if not clean:
                continue
            kept.append(clean)
            status = ("candidate" if candidate_only else
                      ("active" if clean["confidence"] >= ACTIVE_CONFIDENCE
                       else "candidate"))
            memory_id, created = store.add_memory(
                conn, clean["content"], clean["kind"], scope=clean["scope"],
                evidence=clean["evidence"], confidence=clean["confidence"],
                source="archive_extract",
                source_ref=clean["quote"], batch_id=batch_id, status=status)
            if memory_id and created:
                added += 1
            elif memory_id:
                merged += 1
        memory_batches.update_chunk(conn, key, status="done", facts_json=kept)
    return {"ok": True, "messages": len(messages), "chunks": len(chunks),
            "planned": len(planned), "calls": calls, "added": added,
            "merged": merged, "failed": failed}
