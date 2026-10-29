"""对话主体：SSE 流、停止、写操作确认。"""
from __future__ import annotations

import dataclasses
import queue
import threading
import time
import uuid

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from learnsys import agent, diagnostics, store
from learnsys.agent import cost as agent_cost, debug_intent
from learnsys.agent.events import AgentEvent
from learnsys.llm.config import load_config
from learnsys.context import ContextSnapshot
from learnsys.services import home as home_service
from learnsys.server.security import require_token
from .common import _load_history, _sse, _trace_event
from .state import (_ACTIVE, _ACTIVE_LOCK, _ACTIVE_RUNS, _CONFIRM, _CONFIRM_LOCK,
                    CONFIRM_WAIT_SECONDS)

router = APIRouter()

_RUN_END = object()      # 这一轮结束（落库已完成）
_QUEUE_TICK = object()   # 队列暂时没事件：让订阅循环回去检查客户端还在不在


def _take_event(events: queue.Queue):
    """带超时地取一个事件；超时返回哨兵，订阅循环据此轮询断连。"""
    try:
        return events.get(timeout=0.25)
    except queue.Empty:
        return _QUEUE_TICK


def _title_for(message: str) -> str:
    """会话标题：取第一行有内容的文字，不把整个题面/代码的头 30 字塞进侧栏。"""
    for line in str(message or "").splitlines():
        line = " ".join(line.split())
        if line:
            return line[:30]
    return "新对话"


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
    recording_id: int | None = None  # 从录像挂载：后端取这段转写，前端不搬正文
    module: str = "ask"          # ask / review / quiz ...（会话分组用，不进入时间线标题）
    internal: bool = False       # 插件内部提示词：保留会话上下文，但不记成一条「问答」
    surface: str = "ask"         # ask / cet6 / materials ...
    context_snapshot: dict | None = None   # 结构化上下文，<= 20KB
    result_id: int = 0               # 引用已有结果资产（分析/翻译），不复制正文


class StopRequest(BaseModel):
    conversation_id: int | None = None
    run_id: str = ""            # 精确停止某一轮；为空时退回按会话停（旧前端兼容）


class ConfirmRequest(BaseModel):
    run_id: str
    request_id: str
    approve: bool = False


@router.post("/api/agent/chat")
def chat(req: ChatRequest, request: Request, _=Depends(require_token)):
    """一次对话；SSE 逐事件返回。

    **运行与连接解耦**：模型在后台线程里跑，SSE 只是一个订阅者。
    浏览器切页 / 刷新 / 网络抖动导致订阅断开时，只停止发送，不停止思考；
    这一轮会继续跑完并落库，回到问一问能看到完整回答。
    真要停下，走 /api/agent/stop（按 run_id 精确命中）。
    """
    snapshot = None
    if req.context_snapshot:
        try:
            snapshot = ContextSnapshot.from_dict(req.context_snapshot)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
    module = "cet6" if req.surface == "cet6" else (req.module or "ask")
    origin = ("video" if req.surface == "video"
              else ("cet6" if req.surface == "cet6" else "ask"))
    recording_id = int(req.recording_id or 0)
    context_text = snapshot.render_text() if snapshot else req.context
    context_title = "当前学习上下文" if req.surface == "cet6" else ""
    conn = store.connect()
    try:
        conv_id = req.conversation_id
        if conv_id is not None and store.get_conversation(conn, conv_id) is None:
            conv_id = None
        new_conv = conv_id is None
        if recording_id and not store.session_exists(conn, recording_id):
            recording_id = 0
        if conv_id is None:
            conv_id = store.create_conversation(
                conn, title=_title_for(req.message),
                module=module, mode=req.mode,
                origin=origin, recording_id=recording_id)
        # 先取旧账（含已有摘要），再记这一问。有摘要才放宽到 8 轮。
        conversation_row = store.get_conversation(conn, conv_id)
        history_summary = (str(conversation_row[4] or "").strip()
                           if conversation_row is not None else "")
        history = _load_history(conn, conv_id,
                                turns=8 if history_summary else 4)
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
        if recording_id:
            recording = store.get_recording(conn, recording_id)
            if recording is None:
                recording_id = 0
            else:
                text = store.recording_transcript(conn, recording_id, cap=12000)
                if text:
                    # 只把真实转写当背景资料；没有转写就什么都不加 —— 否则模型会
                    # 主动评论「课堂转写是空的」，把普通闲聊也带偏（2026-10-25 真机）。
                    context_text += (
                        "\n\n【录像转写（背景资料，只在问题需要时引用；"
                        "不要主动评论转写是否完整）】\n" + text)
                if new_conv and not req.internal:
                    store.add_event(conn, "video", "ask", recording["title"],
                                    {"session_id": recording_id,
                                     "conversation_id": conv_id},
                                    ref_id=recording_id)
        store.add_message(conn, conv_id, "user", {
            "text": req.message,
            "material_id": material_id,
            "recording_id": recording_id,
            "surface": req.surface,
            "context_snapshot": req.context_snapshot,
            "result_id": req.result_id,
        }, result_id=req.result_id)
    except Exception:
        conn.close()
        raise

    # 个人状态：每轮自动带入，不依赖模型主动调工具；agent 包只收这段字符串。
    try:
        personal_state = home_service.agent_state(conn)
    except Exception as exc:
        diagnostics.log_swallow("个人状态注入", exc)
        personal_state = ""

    # 用户明确要求跑 / 粘贴代码在调试：沙箱内运行属于回答的一部分，不再弹确认。
    intent = debug_intent.detect(req.message)
    auto_run_code = bool(req.surface == "ask" and req.mode != "quiz"
                         and (intent["code_debug"] or intent["run_requested"]))

    cfg = load_config()
    if req.surface == "cet6":
        # 六级里的「直接问」是精听现场提问，固定快模型 + 不思考；深度问答仍走主模型。
        cfg = dataclasses.replace(cfg, model=cfg.fast_model or cfg.model,
                                  thinking=False, speed="fast")
    started = time.monotonic()
    run_id = uuid.uuid4().hex
    started_at = store.now()
    abort = threading.Event()
    key = str(conv_id)
    with _ACTIVE_LOCK:
        _ACTIVE[key] = abort
        _ACTIVE_RUNS[run_id] = abort

    events: queue.Queue = queue.Queue()

    def worker():
        """真正跑模型的地方：与 HTTP 连接无关。

        连接断了只会让下面的订阅循环退出，这里照常跑完、照常落库。
        """
        final = ""
        error = ""
        thinking = ""
        partial = ""             # 已流出的正文（异常时也要保住，不能只留一句报错）
        first_ms = None          # 首个可见片段（思考或正文）到达的耗时，闸门要量「首 token」
        usage: dict = {}
        steps = 0
        model_calls = 0
        tool_count = 0
        error_count = 0
        stop_reason = ""
        check_ok = None
        routed_model = ""
        usage_by_model: dict = {}
        run_cost = 0.0
        run_currency = ""
        trace: list[dict] = []
        persisted = False

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

        def persist():
            """落库只做一次；done 时先落库再通知前端，回来重读能看到完整回答。"""
            nonlocal persisted
            if persisted:
                return
            persisted = True
            schedule_post = not req.internal
            try:
                total_ms = int((time.monotonic() - started) * 1000)
                if run_cost or usage_by_model:
                    cost, currency = run_cost, run_currency
                else:
                    cost, currency, _ = agent_cost.estimate(usage, cfg,
                                                            str(routed_model or cfg.model))
                store.add_agent_run(
                    conn, run_id=run_id, conversation_id=conv_id,
                    question=req.message[:200], model=routed_model or cfg.model or "",
                    mode=req.mode, started_at=started_at,
                    finished_at=store.now(), first_ms=first_ms,
                    total_ms=total_ms, steps=steps, stop_reason=stop_reason,
                    usage=usage, trace=trace[:200], check_ok=check_ok,
                    error=error, tool_count=tool_count,
                    model_calls=model_calls, error_count=error_count,
                    cost=cost, currency=currency)
                if final:
                    # messages 是会话真相；asks 是时间线/检索索引（同一轮问答的派生）。
                    # 先写真相，再写索引；索引失败不影响会话历史。
                    store.add_message(conn, conv_id, "assistant",
                                      {"text": final, "thinking": thinking,
                                       "run_id": run_id})
                    if not req.internal:       # 复盘/测验的提示词不算「我问过什么」
                        store.add_ask(
                            conn, req.message, final, total_ms,
                            routed_model or cfg.model or "agent",
                            kind="image" if req.image_path else "text",
                            image_path=req.image_path or "", thread=str(conv_id),
                            conversation_id=conv_id, first_ms=first_ms)
                elif error:
                    payload = {"error": error, "run_id": run_id}
                    if partial.strip():
                        # 中途断流 / 模型出错：已经写给用户看的正文不能丢。
                        payload["text"] = partial
                        payload["interrupted"] = True
                    store.add_message(conn, conv_id, "assistant", payload)
                elif partial.strip():
                    # 用户点停止时 agent 会发 done(aborted)；这里兜住没有 done 的极端情况。
                    store.add_message(conn, conv_id, "assistant",
                                      {"text": partial, "run_id": run_id,
                                       "interrupted": True})
            except Exception as exc:
                diagnostics.log_swallow("对话落库（消息/问答）", exc)
                schedule_post = False
            conn.close()
            if schedule_post:
                # 每 4 条消息在后台生成摘要 + 抽长期记忆；主连接已关，不抢写锁。
                try:
                    from learnsys.agent import post_turn
                    post_turn.schedule(conv_id, cfg.data_root)
                except Exception as exc:
                    diagnostics.log_swallow("会话摘要/记忆排程", exc)

        try:
            events.put(("start", "", {"conversation_id": conv_id,
                                      "model": cfg.model, "run_id": run_id}))
            agent_request = agent.AgentRequest(
                message=req.message,
                history=history,
                history_summary=history_summary,
                personal_state=personal_state,
                image_path=req.image_path,
                extra_images=list(req.extra_images or []),
                context=context_text,
                context_title=context_title,
                attachment_name=attachment_name,
                attachment_text=attachment_text,
                mode=req.mode,
                module=module,
                surface=req.surface,
                conversation_id=conv_id,
                conversation_key=str(conv_id),
                material_id=material_id or 0,
                auto_run_code=auto_run_code,
            )
            for event in agent.run(agent_request, cfg=cfg, abort=abort,
                                   confirm=ask_confirm):
                if first_ms is None and event.kind in ("text", "thinking"):
                    first_ms = int((time.monotonic() - started) * 1000)
                data = dict(event.data or {})
                if event.kind == "confirm":
                    data["run_id"] = run_id
                trace_item = _trace_event(event)
                if trace_item is not None:
                    trace.append(trace_item)
                if event.kind == "text":
                    partial += event.text or ""
                if event.kind == "route":
                    routed_model = str(data.get("model") or "") or routed_model
                elif event.kind == "check":
                    check_ok = bool(data.get("ok"))
                elif event.kind == "tool_end":
                    if data.get("ok") is False:
                        error_count += 1
                elif event.kind == "done":
                    final = str(data.get("text") or "")
                    thinking = str(data.get("thinking") or "")
                    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                    usage_by_model = (data.get("usage_by_model")
                                      if isinstance(data.get("usage_by_model"), dict) else {})
                    run_cost = float(data.get("cost") or 0)
                    run_currency = str(data.get("currency") or "")
                    steps = int(data.get("steps") or 0)
                    model_calls = int(data.get("model_calls") or 0)
                    tool_count = int(data.get("tool_calls") or 0)
                    stop_reason = str(data.get("stop_reason") or "")
                    persist()               # 先写库，再让前端收到 done
                elif event.kind == "error":
                    error = event.text
                    error_count += 1
                events.put((event.kind, event.text, data))
        except Exception as exc:                 # 不让异常把这一轮撕成半截
            error = f"服务端出错：{exc}"
            events.put(("error", error, {}))
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.pop(key, None)
                _ACTIVE_RUNS.pop(run_id, None)
            persist()
            events.put(_RUN_END)

    threading.Thread(target=worker, daemon=True, name=f"chat-{run_id}").start()

    async def subscribe():
        """只负责把事件转给浏览器；断开就退订，不碰后台那一轮。"""
        while True:
            if await request.is_disconnected():
                return
            item = await anyio.to_thread.run_sync(_take_event, events)
            if item is _QUEUE_TICK:
                continue
            batch = [item]
            while True:
                try:
                    batch.append(events.get_nowait())
                except queue.Empty:
                    break
            for event in batch:
                if event is _RUN_END:
                    return
                kind, text, data = event
                yield _sse(kind, text, data)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(subscribe(), media_type="text/event-stream", headers=headers)


@router.post("/api/agent/stop")
def stop(req: StopRequest, _=Depends(require_token)):
    """停止一轮运行：优先按 run_id 精确命中，旧前端仍可按会话停。"""
    with _ACTIVE_LOCK:
        if req.run_id:
            event = _ACTIVE_RUNS.get(str(req.run_id))
            targets = [event] if event is not None else []
        elif req.conversation_id is not None:
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
