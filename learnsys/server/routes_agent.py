"""Agent 接口：SSE 对话、停止、会话列表 / 历史。"""
from __future__ import annotations

import dataclasses
import json
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from learnsys import agent, store
from learnsys.agent.config import load_config
from learnsys.context import ContextSnapshot
from learnsys.server.security import require_token

router = APIRouter()

_ACTIVE: dict[str, threading.Event] = {}
_ACTIVE_LOCK = threading.Lock()

# 写操作确认：key = "run_id:request_id"；等用户点「允许 / 拒绝」或超时。
_CONFIRM: dict[str, dict] = {}
_CONFIRM_LOCK = threading.Lock()
CONFIRM_WAIT_SECONDS = 120

_TRACE_KINDS = {"plan", "plan_update", "tool_start", "tool_end", "confirm",
                "check", "rewrite", "activity", "error"}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: int | None = None
    mode: str = "explain"
    image_path: str | None = None
    extra_images: list[str] = Field(default_factory=list)
    context: str = ""
    attachment_name: str = ""
    attachment_text: str = ""
    material_id: int | None = None   # 从资料库挂载：正文由后端按 id 取，前端不搬几十万字
    attach_material: bool = True     # False = 只给错题归档用，不把正文塞进这一轮
    module: str = "ask"          # ask / review / quiz ...（会话分组用，不进入时间线标题）
    internal: bool = False       # 插件内部提示词：保留会话上下文，但不记成一条「问答」
    surface: str = "ask"         # ask / cet6 / materials ...
    context_snapshot: dict | None = None   # 结构化上下文，<= 20KB


class StopRequest(BaseModel):
    conversation_id: int | None = None


class ConfirmRequest(BaseModel):
    run_id: str
    request_id: str
    approve: bool = False


def _sse(kind: str, text: str = "", data: dict | None = None) -> str:
    return "data: " + json.dumps(
        {"kind": kind, "text": text, "data": data or {}}, ensure_ascii=False) + "\n\n"


def _clip(value, cap: int = 600, depth: int = 0):
    """流水里的参数/结果摘要：截断，不把整份资料或隐私正文写进去。"""
    if depth > 4:
        return "…"
    if isinstance(value, str):
        return value if len(value) <= cap else value[:cap] + "…"
    if isinstance(value, dict):
        return {str(key): _clip(item, cap, depth + 1)
                for key, item in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_clip(item, cap, depth + 1) for item in list(value)[:20]]
    return value


def _trace_event(event) -> dict | None:
    if event.kind not in _TRACE_KINDS:
        return None
    return {"kind": event.kind, "text": _clip(event.text or "", 400),
            "data": _clip(event.data or {})}


def _load_history(conn, conversation_id: int, turns: int = 4) -> list[tuple[str, str]]:
    """把落库的消息配成「问/答」对，喂给 Agent 做多轮上下文。

    只收有正文的问答；出错/中断的消息跳过。兼容 v1 的纯字符串 content。
    """
    pairs: list[tuple[str, str]] = []
    question = ""
    for message in store.conversation_messages(conn, conversation_id):
        content = message.get("content")
        if message.get("role") == "user":
            if isinstance(content, dict):
                question = str(content.get("text") or "")
            elif isinstance(content, str):
                question = content
        elif message.get("role") == "assistant" and question:
            if isinstance(content, dict):
                answer = str(content.get("text") or "")
            elif isinstance(content, str):
                answer = content
            else:
                answer = ""
            if answer.strip():
                pairs.append((question, answer))
            question = ""
    return pairs[-max(1, turns):]


@router.post("/api/agent/chat")
def chat(req: ChatRequest, _=Depends(require_token)):
    """一次对话；SSE 逐事件返回。客户端断开时生成器会关连接、DB 连接也会关。"""
    snapshot = None
    if req.context_snapshot:
        try:
            snapshot = ContextSnapshot.from_dict(req.context_snapshot)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
    module = "cet6" if req.surface == "cet6" else (req.module or "ask")
    context_text = snapshot.render_text() if snapshot else req.context
    context_title = "当前学习上下文" if req.surface == "cet6" else ""
    conn = store.connect()
    try:
        conv_id = req.conversation_id
        if conv_id is not None and store.get_conversation(conn, conv_id) is None:
            conv_id = None
        new_conv = conv_id is None
        if conv_id is None:
            conv_id = store.create_conversation(
                conn, title=req.message.strip()[:30] or "新对话",
                module=module, mode=req.mode)
        history = _load_history(conn, conv_id)       # 先取旧账，再记这一问
        material_id = req.material_id
        material_title = ""
        attachment_name = req.attachment_name
        attachment_text = req.attachment_text
        if material_id:
            material = store.get_material(conn, material_id)
            if material is not None and material.get("status") == "active":
                material_title = material["title"]
                if req.attach_material:
                    attachment_name = material["title"]
                    attachment_text = material["body"]
                    store.touch_material(conn, material_id)
                    if new_conv and not req.internal:
                        store.add_event(conn, "materials", "ask", material_title,
                                        {"material_id": material_id,
                                         "conversation_id": conv_id})
            else:
                material_id = None
        store.add_message(conn, conv_id, "user", {
            "text": req.message,
            "material_id": material_id,
            "surface": req.surface,
            "context_snapshot": req.context_snapshot,
        })
    except Exception:
        conn.close()
        raise

    cfg = load_config()
    if req.surface == "cet6":
        # 六级里的「直接问」是精听现场提问，固定快模型 + 不思考；深度问答仍走主模型。
        cfg = dataclasses.replace(cfg, model=cfg.fast_model or cfg.model,
                                  thinking=False, speed="fast")
    abort = threading.Event()
    key = str(conv_id)
    with _ACTIVE_LOCK:
        _ACTIVE[key] = abort
    started = time.monotonic()
    run_id = uuid.uuid4().hex
    started_at = store.now()

    def stream():
        final = ""
        error = ""
        thinking = ""
        first_ms = None          # 首个可见片段（思考或正文）到达的耗时，闸门要量「首 token」
        usage: dict = {}
        steps = 0
        stop_reason = ""
        check_ok = None
        trace: list[dict] = []

        def ask_confirm(request_id: str, tool_name: str, args: dict) -> bool:
            """阻塞等界面点确认；超时 / 停止都按拒绝处理。"""
            slot = {"event": threading.Event(), "approved": False}
            slot_key = f"{run_id}:{request_id}"
            with _CONFIRM_LOCK:
                _CONFIRM[slot_key] = slot
            try:
                deadline = time.monotonic() + CONFIRM_WAIT_SECONDS
                while time.monotonic() < deadline:
                    if abort.is_set():
                        return False
                    if slot["event"].wait(0.2):
                        return bool(slot["approved"])
                return False
            finally:
                with _CONFIRM_LOCK:
                    _CONFIRM.pop(slot_key, None)

        try:
            yield _sse("start", data={"conversation_id": conv_id, "model": cfg.model,
                                      "run_id": run_id})
            request = agent.AgentRequest(
                message=req.message,
                history=history,
                image_path=req.image_path,
                extra_images=list(req.extra_images or []),
                context=context_text,
                context_title=context_title,
                attachment_name=attachment_name,
                attachment_text=attachment_text,
                mode=req.mode,
                module=module,
                conversation_id=conv_id,
                conversation_key=str(conv_id),
                material_id=material_id or 0,
            )
            for event in agent.run(request, cfg=cfg, abort=abort,
                                   confirm=ask_confirm):
                if first_ms is None and event.kind in ("text", "thinking"):
                    first_ms = int((time.monotonic() - started) * 1000)
                data = dict(event.data or {})
                if event.kind == "confirm":
                    data["run_id"] = run_id
                trace_item = _trace_event(event)
                if trace_item is not None:
                    trace.append(trace_item)
                yield _sse(event.kind, event.text, data)
                if event.kind == "check":
                    check_ok = bool(data.get("ok"))
                elif event.kind == "done":
                    final = str(data.get("text") or "")
                    thinking = str(data.get("thinking") or "")
                    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                    steps = int(data.get("steps") or 0)
                    stop_reason = str(data.get("stop_reason") or "")
                elif event.kind == "error":
                    error = event.text
        except Exception as exc:                 # 不让异常把 SSE 流撕成半截
            error = f"服务端出错：{exc}"
            yield _sse("error", error)
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.pop(key, None)
            try:
                total_ms = int((time.monotonic() - started) * 1000)
                store.add_agent_run(
                    conn, run_id=run_id, conversation_id=conv_id,
                    question=req.message, model=cfg.model or "",
                    mode=req.mode, started_at=started_at,
                    finished_at=store.now(), first_ms=first_ms,
                    total_ms=total_ms, steps=steps, stop_reason=stop_reason,
                    usage=usage, trace=trace[:200], check_ok=check_ok,
                    error=error)
                if final:
                    store.add_message(conn, conv_id, "assistant",
                                      {"text": final, "thinking": thinking,
                                       "run_id": run_id})
                    if not req.internal:       # 复盘/测验的提示词不算「我问过什么」
                        store.add_ask(
                            conn, req.message, final, total_ms, cfg.model or "agent",
                            kind="image" if req.image_path else "text",
                            image_path=req.image_path or "", thread=str(conv_id),
                            conversation_id=conv_id, first_ms=first_ms)
                elif error:
                    store.add_message(conn, conv_id, "assistant", {"error": error})
            except Exception:
                pass
            conn.close()

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)


@router.post("/api/agent/stop")
def stop(req: StopRequest, _=Depends(require_token)):
    with _ACTIVE_LOCK:
        if req.conversation_id is not None:
            event = _ACTIVE.get(str(req.conversation_id))
            targets = [event] if event is not None else []
        else:
            targets = list(_ACTIVE.values())
        for event in targets:
            event.set()
    return {"stopped": len(targets)}


@router.post("/api/agent/confirm")
def confirm(req: ConfirmRequest, _=Depends(require_token)):
    """用户对写操作点「允许 / 拒绝」；确认请求 120 秒过期。"""
    slot_key = f"{req.run_id}:{req.request_id}"
    with _CONFIRM_LOCK:
        slot = _CONFIRM.get(slot_key)
    if slot is None:
        raise HTTPException(status_code=404,
                            detail="这条确认请求已过期或不存在（可能已超时）")
    slot["approved"] = bool(req.approve)
    slot["event"].set()
    return {"ok": True, "approved": bool(req.approve)}


@router.get("/api/agent/runs")
def agent_runs(conversation_id: int = 0, limit: int = 20,
               _=Depends(require_token)):
    conn = store.connect()
    try:
        return {"items": store.list_agent_runs(
            conn, conversation_id=conversation_id, limit=limit)}
    finally:
        conn.close()


@router.get("/api/agent/runs/{run_id}")
def agent_run(run_id: str, _=Depends(require_token)):
    conn = store.connect()
    try:
        row = store.get_agent_run(conn, run_id=run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="运行记录不存在")
        return row
    finally:
        conn.close()


@router.get("/api/conversations")
def conversations(limit: int = 20, module: str = "ask", _=Depends(require_token)):
    conn = store.connect()
    try:
        return {"items": store.list_conversations(
            conn, limit=limit, module="" if module == "all" else module)}
    finally:
        conn.close()


@router.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        row = store.get_conversation(conn, conversation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = store.conversation_messages(conn, conversation_id)
        return {
            "id": row[0], "title": row[1] or "", "module": row[2] or "ask",
            "mode": row[3] or "explain", "summary": row[4] or "",
            "started_at": row[5] or "", "updated_at": row[6] or "",
            "messages": messages,
        }
    finally:
        conn.close()
