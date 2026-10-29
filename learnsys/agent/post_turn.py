"""会话收尾：生成摘要 + 抽取长期记忆（同一次模型调用）。

触发：非 internal 会话每完成 4 条消息（2 轮问答）跑一次后台线程。
口径：
- 摘要写回 `conversations.summary`，下一轮起注入系统提示词，历史窗口 4 → 8 轮；
- **滚动合并**：每次把「已有摘要 + 最近 12 条」合成新摘要，不再覆盖式只看最近几轮；
  长会话的早期结论不会在第 16 条消息之后被挤丢；
- 记忆只收**明确、跨会话有效**的偏好/规矩，自动生效（负责人 2026-10-27 拍板）；
- 一次调用最多 2 条，去重后写入 `agent_memories`；启用条数上限 40；
- 失败只记诊断日志，不影响主回答；模型调用走 `agent/usage.py` 记账。
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
import threading

from learnsys import config, diagnostics, store
from learnsys.agent import usage as agent_usage
from learnsys.core import jsontext
from learnsys.llm import provider_anthropic
from learnsys.llm.config import load_config

EVERY_MESSAGES = 4
RECENT_MESSAGES = 12
CLIP_CHARS = 600
MAX_NEW_MEMORIES = 2
MAX_ACTIVE_MEMORIES = 40
MAX_MEMORY_CHARS = 120
MIN_MEMORY_CHARS = 6

_RUNNING: set[int] = set()
_LOCK = threading.Lock()

SYSTEM = """你是「学习工作台」的会话整理器。读「已有会话摘要」和「最近对话」，只输出一个 JSON 对象：
{"summary": "不超过 200 字的中文摘要", "memories": [{"content": "一条长期规矩", "kind": "preference"}]}

摘要要求：
- 写清用户在学什么、卡在哪、已经解决了什么、下一步可以做什么；
- **必须把旧摘要和最近对话合并成一份新摘要**：旧摘要里仍然有效的信息保留，
  已经过时、被推翻或被用户纠正的内容删掉；不能只写最近几轮而丢掉更早的内容；
- 只陈述对话里真实出现的内容，不编造；没有实质内容就给空串。

记忆要求：
- 只收用户**明确表达、跨会话有效**的偏好或规矩（出现「以后 / 每次 / 默认 / 我习惯 / 记住 / 不要 / 我喜欢」等）；
- 不收一次任务细节、临时安排、第三方隐私、密钥/密码/路径；
- 每条是完整的一句话，最多 100 字；最多 2 条；没有就 []；
- 不要重复【已有长期记忆】里已有的意思。
只输出 JSON，不要解释。"""


def _db(data_root) -> pathlib.Path:
    return pathlib.Path(data_root or config.DATA_ROOT) / "learning.db"


def _transcript(conn, conversation_id: int) -> str:
    lines: list[str] = []
    for message in store.conversation_messages(conn, conversation_id)[-RECENT_MESSAGES:]:
        content = message.get("content")
        if isinstance(content, dict):
            if content.get("error") or content.get("interrupted"):
                continue          # 半截回答不当成事实写进摘要
            text = str(content.get("text") or "")
        elif isinstance(content, str):
            text = content
        else:
            text = ""
        text = " ".join(text.split())
        if not text:
            continue
        role = "用户" if message.get("role") == "user" else "助手"
        lines.append(f"{role}：{text[:CLIP_CHARS]}")
    return "\n".join(lines)


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "").lower())


def _existing(conn) -> list[str]:
    try:
        return [item["content"] for item in store.list_memories(conn, limit=MAX_ACTIVE_MEMORIES)]
    except Exception:
        return []


def _duplicate(content: str, existing: list[str]) -> bool:
    norm = _normalize(content)
    if not norm:
        return True
    for item in existing:
        other = _normalize(item)
        if not other:
            continue
        if norm == other:
            return True
        shorter, longer = sorted((norm, other), key=len)
        if len(shorter) >= 6 and shorter in longer:
            return True
    return False


def _save_memories(conn, items) -> int:
    existing = _existing(conn)
    room = max(0, MAX_ACTIVE_MEMORIES - len(existing))
    saved = 0
    for item in items or []:
        if saved >= min(MAX_NEW_MEMORIES, room):
            break
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content") or "").split())[:MAX_MEMORY_CHARS]
        if len(content) < MIN_MEMORY_CHARS or _duplicate(content, existing):
            continue
        kind = str(item.get("kind") or "preference")
        if kind not in ("preference", "rule", "identity"):
            kind = "preference"
        try:
            store.add_memory(conn, content, kind=kind)
        except Exception as exc:            # noqa: BLE001
            diagnostics.log_swallow("自动记忆写入", exc)
            continue
        existing.append(content)
        saved += 1
    return saved


def _parse(text: str) -> dict:
    try:
        data = jsontext.parse_object(text)
    except ValueError:
        return {}
    summary = " ".join(str(data.get("summary") or "").split())[:400]
    memories = data.get("memories")
    return {"summary": summary, "memories": memories if isinstance(memories, list) else []}


def _generate(conn, conversation_id: int, data_root) -> dict:
    transcript = _transcript(conn, conversation_id)
    if not transcript:
        return {}
    cfg = load_config()
    if not cfg.ready:
        return {}
    from learnsys.agent import budget
    if budget.check(cfg):
        return {}                            # 到了每日上限：后台任务也不发请求
    fast = dataclasses.replace(
        cfg, model=cfg.fast_model or cfg.model, thinking=False,
        max_tokens=min(int(cfg.max_tokens or 700), 700), speed="fast")
    existing = "\n".join(f"- {item}" for item in _existing(conn)) or "（无）"
    conversation = store.get_conversation(conn, int(conversation_id))
    old_summary = (str(conversation[4] or "").strip()
                   if conversation is not None else "")
    prompt = (f"【已有会话摘要】\n{old_summary or '（无）'}\n\n"
              f"【已有长期记忆】\n{existing}\n\n"
              f"【最近对话】\n{transcript}")
    parts: list[str] = []
    result = None
    for event in provider_anthropic.stream_messages(
            fast, SYSTEM, [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            None, timeout=60.0):
        if event.kind == "text":
            parts.append(event.text)
        elif event.kind == "done":
            result = event.result
    text = (result.text if result is not None and result.text else "".join(parts)).strip()
    if result is not None and getattr(result, "usage", None):
        agent_usage.record(data_root, source="post_turn", model=fast.model,
                           usage=result.usage, cfg=fast)
    return _parse(text)


def run_once(conversation_id: int, data_root) -> dict:
    """同步跑一次（测试与回填脚本直接调用）。"""
    path = _db(data_root)
    conn = store.connect(path)
    try:
        payload = _generate(conn, int(conversation_id), data_root)
        if not payload:
            return {"summary": "", "memories": 0}
        summary = payload.get("summary") or ""
        if summary:
            store.set_conversation_summary(conn, int(conversation_id), summary)
        saved = _save_memories(conn, payload.get("memories") or [])
        return {"summary": summary, "memories": saved}
    finally:
        conn.close()


def _worker(conversation_id: int, data_root) -> None:
    try:
        run_once(conversation_id, data_root)
    except Exception as exc:                # noqa: BLE001 —— 后台任务失败不能影响问答
        diagnostics.log_swallow("会话摘要/记忆抽取", exc, data_root=data_root)
    finally:
        with _LOCK:
            _RUNNING.discard(conversation_id)


def schedule(conversation_id: int, data_root, *, internal: bool = False) -> bool:
    """满足「每 4 条消息」就起一个后台线程；返回是否真的排上了。"""
    if internal or not conversation_id:
        return False
    try:
        conn = store.connect(_db(data_root))
        try:
            count = len(store.conversation_messages(conn, int(conversation_id)))
            conversation = store.get_conversation(conn, int(conversation_id))
        finally:
            conn.close()
    except Exception:
        return False
    if count < EVERY_MESSAGES or count % EVERY_MESSAGES != 0 or conversation is None:
        return False
    with _LOCK:
        if conversation_id in _RUNNING:
            return False
        _RUNNING.add(conversation_id)
    threading.Thread(target=_worker, args=(int(conversation_id), data_root),
                     daemon=True, name=f"post-turn-{conversation_id}").start()
    return True
