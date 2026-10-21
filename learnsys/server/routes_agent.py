"""Agent 接口：SSE 对话、停止、会话列表 / 历史。"""
from __future__ import annotations

import dataclasses
import json
import threading
import time

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


def _sse(kind: str, text: str = "", data: dict | None = None) -> str:
    return "data: " + json.dumps(
        {"kind": kind, "text": text, "data": data or {}}, ensure_ascii=False) + "\n\n"


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
        # 六级里的「直接问」是精听现场提问，固定快模型；深度问答仍走主模型。
        cfg = dataclasses.replace(cfg, model=cfg.fast_model or cfg.model)
    abort = threading.Event()
    key = str(conv_id)
    with _ACTIVE_LOCK:
        _ACTIVE[key] = abort
    started = time.monotonic()

    def stream():
        final = ""
        error = ""
        thinking = ""
        first_ms = None          # 首个可见片段（思考或正文）到达的耗时，闸门要量「首 token」
        try:
            yield _sse("start", data={"conversation_id": conv_id, "model": cfg.model})
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
            for event in agent.run(request, cfg=cfg, abort=abort):
                if first_ms is None and event.kind in ("text", "thinking"):
                    first_ms = int((time.monotonic() - started) * 1000)
                yield _sse(event.kind, event.text, event.data)
                if event.kind == "done":
                    final = str(event.data.get("text") or "")
                    thinking = str(event.data.get("thinking") or "")
                elif event.kind == "error":
                    error = event.text
        except Exception as exc:                 # 不让异常把 SSE 流撕成半截
            error = f"服务端出错：{exc}"
            yield _sse("error", error)
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.pop(key, None)
            try:
                if final:
                    ms = int((time.monotonic() - started) * 1000)
                    store.add_message(conn, conv_id, "assistant",
                                      {"text": final, "thinking": thinking})
                    if not req.internal:       # 复盘/测验的提示词不算「我问过什么」
                        store.add_ask(
                            conn, req.message, final, ms, cfg.model or "agent",
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
