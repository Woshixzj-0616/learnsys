"""后台线程：问答流、占用统计、答案底边拖拽条。"""
from __future__ import annotations

import threading
import time
import uuid

from PySide6 import QtCore, QtWidgets

from learnsys import agent, diagnostics, store
from learnsys.agent import answer_audit
from learnsys.agent import tools as agent_tools
from learnsys.agent.run_record import trace_event
from learnsys.ask import usage
from learnsys.llm.config import load_config

from .common import GRIP_H

# 快捷栏每轮都带个人状态；60 秒内复用，避免每次敲 Alt+Q 都开库重算。
PERSONAL_STATE_TTL = 60.0
_STATE_LOCK = threading.Lock()
_STATE_CACHE = {"at": None, "text": ""}


def reset_personal_state_cache() -> None:
    with _STATE_LOCK:
        _STATE_CACHE.update(at=None, text="")


def _load_personal_state() -> str:
    """真正查库的动作；放单独函数方便测试替换。"""
    from learnsys.services import home

    conn = store.connect()
    try:
        return home.agent_state(conn)
    finally:
        conn.close()


def personal_state(now: float | None = None) -> str:
    """给快捷栏本轮的个人状态；60 秒缓存，失败不缓存、下一轮重试。"""
    moment = time.monotonic() if now is None else float(now)
    with _STATE_LOCK:
        cached_at = _STATE_CACHE["at"]
        if cached_at is not None and moment - cached_at < PERSONAL_STATE_TTL:
            return str(_STATE_CACHE["text"] or "")
    try:
        text = _load_personal_state()
    except Exception:
        return ""
    with _STATE_LOCK:
        _STATE_CACHE.update(at=moment, text=text)
    return text


class _UsageWorker(QtCore.QThread):
    """占用数字在后台算 —— `usage.report()` 要整树 walk 盘，放主线程会卡界面。"""

    done = QtCore.Signal(object)     # Usage 实例，或 Exception

    def run(self):
        try:
            self.done.emit(usage.summary())
        except Exception as exc:                 # 后台线程里的异常别吞
            self.done.emit(exc)


class _AskWorker(QtCore.QThread):
    chunk = QtCore.Signal(str, bool)      # 流式：(新到的字, True = 整段替换/ False = 追加)
    thinking = QtCore.Signal(str)         # 思考过程增量（横栏可以点开看）
    done = QtCore.Signal(str)             # 完整答案（含已流出的部分）
    failed = QtCore.Signal(str)           # 失败原因（若已有部分文本，界面会留着）
    activity = QtCore.Signal(str)         # 状态行的一句话：看图 / 查记录 / 推理中
    confirm_needed = QtCore.Signal(object)   # 写操作要确认：{request_id, tool, summary}
    deep_suggested = QtCore.Signal(str)   # 这题值得深入讲：complex / audit

    def __init__(self, image_path: str, question: str, history, parent=None, context: str = "",
                 extra_images: list[str] | None = None, mode: str = "explain"):
        super().__init__(parent)
        self._image_path = image_path
        self._question = question
        self._history = history
        self._context = context      # 课上转写片段（追问时捎给 AI，界面不显示）
        self._extra_images = list(extra_images or [])  # 复盘/测验附带的图片
        self._mode = mode
        self._system_override = ""     # 电脑助手等非导师任务用
        self._use_tools = True
        self._deep = False             # 用户点了「深入讲」：强模型 + 思考
        self._conversation_key = ""    # 同一轮对话的稳定号，测验收错题去重用
        self._run_info: dict = {}      # 给界面落库用的本轮信息（模型/首字/总时长）
        self._cancelled = False
        self._abort = threading.Event()       # 传给 Agent：一置位就收摊
        self._sink: list = []                 # 底层响应，cancel 时 close 掐断连接
        self._last_activity = ""              # 同一句话只发一次（思考增量每片都来，别刷屏）
        self._confirm_slot: dict | None = None

    def _confirm_write(self, request_id: str, tool_name: str, args: dict) -> bool:
        """写操作：发到主线程弹窗，等用户点「允许 / 拒绝」（120 秒超时=拒绝）。"""
        slot = {"event": threading.Event(), "ok": False}
        self._confirm_slot = slot
        self.confirm_needed.emit({
            "request_id": request_id, "tool": tool_name,
            "summary": agent_tools.write_summary(tool_name, args),
        })
        slot["event"].wait(120)
        return bool(slot["ok"])

    def _say(self, text: str) -> None:
        text = str(text or "")
        if text and text != self._last_activity:
            self._last_activity = text
            self.activity.emit(text)

    def cancel(self) -> None:
        """这一轮不要了（用户开了新会话 / 清空）—— **连连接一起掐**，
        不然 HTTP 会一直挂到 90 秒超时才释放。
        """
        self._cancelled = True
        self._abort.set()
        for resp in self._sink:
            try:
                resp.close()
            except Exception:
                pass

    def run(self):
        parts: list[str] = []
        final = ""
        started = time.monotonic()
        started_at = store.now()
        run_id = uuid.uuid4().hex
        stats = {
            "first_ms": None, "model": "", "steps": 0, "model_calls": 0,
            "tool_count": 0, "stop_reason": "", "usage": {}, "cost": 0.0,
            "currency": "", "check_ok": None, "error": "", "error_count": 0,
            "trace": [],
        }
        recorded = [False]

        def build_info() -> dict:
            model = stats["model"]
            if not model:
                try:
                    model = load_config().model
                except Exception:
                    model = ""
            info = {
                "run_id": run_id,
                "model": model,
                "first_ms": stats["first_ms"],
                "total_ms": int((time.monotonic() - started) * 1000),
                "deep": bool(self._deep),
                "steps": stats["steps"],
                "model_calls": stats["model_calls"],
                "tool_count": stats["tool_count"],
                "stop_reason": stats["stop_reason"],
                "error": stats["error"],
            }
            self._run_info = info       # 界面在 done 槽里读它，必须早于 done.emit
            return info

        def write_run(info: dict) -> None:
            """补一条 agent_runs；失败只记诊断，绝不影响回答。"""
            if recorded[0]:
                return
            recorded[0] = True
            stop_reason = info["stop_reason"] or (
                "aborted" if self._cancelled else ("error" if info["error"] else ""))
            try:
                conn = store.connect()
                try:
                    store.add_agent_run(
                        conn, run_id=info["run_id"], conversation_id=0,
                        question=self._question[:200], model=info["model"],
                        mode=self._mode, started_at=started_at,
                        finished_at=store.now(), first_ms=info["first_ms"],
                        total_ms=info["total_ms"], steps=info["steps"],
                        stop_reason=stop_reason, usage=stats["usage"],
                        trace=stats["trace"][:200], check_ok=stats["check_ok"],
                        error=info["error"][:500], tool_count=info["tool_count"],
                        model_calls=info["model_calls"],
                        error_count=stats["error_count"], cost=stats["cost"],
                        currency=stats["currency"])
                finally:
                    conn.close()
            except Exception as exc:
                diagnostics.log_swallow("快捷栏运行流水", exc)

        try:
            request = agent.AgentRequest(
                message=self._question,
                history=self._history,
                image_path=self._image_path,
                extra_images=self._extra_images,
                context=self._context,
                personal_state=personal_state(),
                mode=self._mode,
                surface="quickbar",
                system_override=self._system_override,
                use_tools=self._use_tools,
                conversation_key=self._conversation_key,
                deep=self._deep,
            )
            for event in agent.run(request, abort=self._abort, response_sink=self._sink,
                                   confirm=self._confirm_write):
                item = trace_event(event)
                if item:
                    stats["trace"].append(item)
                if stats["first_ms"] is None and event.kind in ("text", "thinking"):
                    stats["first_ms"] = int((time.monotonic() - started) * 1000)
                if self._cancelled:
                    stats["stop_reason"] = "aborted"
                    return
                if event.kind == "text":
                    parts.append(event.text)
                    self.chunk.emit(event.text, False)
                elif event.kind == "thinking":
                    self._say("正在推理…")
                    if event.text:
                        self.thinking.emit(event.text)
                elif event.kind == "route":
                    data = event.data or {}
                    if data.get("model"):
                        stats["model"] = str(data["model"])
                    recommended = data.get("recommended") or {}
                    if (not self._deep and str(recommended.get("tier")) == "deep"
                            and str(data.get("tier")) != "deep"):
                        self.deep_suggested.emit("complex")
                elif event.kind == "plan":
                    steps = event.data.get("steps") or []
                    self._say("计划：" + "；".join(
                        f"{index + 1}) {step.get('title', '')}"
                        for index, step in enumerate(steps[:6])))
                elif event.kind == "plan_update":
                    steps = event.data.get("steps") or []
                    index = int(event.data.get("index") or 0)
                    if 0 <= index < len(steps):
                        mark = {"done": "完成", "failed": "失败", "doing": "进行中",
                                "skipped": "跳过"}.get(
                                    str(event.data.get("status")), "")
                        self._say(f"第 {index + 1} 步{mark}：{steps[index].get('title', '')}")
                elif event.kind == "confirm":
                    self._say("等你确认写入…")
                elif event.kind == "check":
                    issues = event.data.get("issues") or []
                    stats["check_ok"] = bool(event.data.get("ok"))
                    self._say("自检通过" if event.data.get("ok")
                              else f"自检发现 {len(issues)} 处引用问题")
                elif event.kind == "rewrite":
                    text = str(event.data.get("text") or "")
                    if text:
                        parts.clear()
                        parts.append(text)
                        self.chunk.emit(text, True)
                        self._say("已按自检结果重写")
                elif event.kind == "activity":
                    if event.text:
                        self._say(event.text)
                elif event.kind == "vision":
                    if event.text:
                        self._say(event.text)
                    elif event.data:
                        used = event.data.get("used_vision")
                        self._say("看图完成（视觉模型）" if used
                                  else "看图完成（只读了文字，没看到图）")
                elif event.kind == "tool_start":
                    label = (event.data.get("label") or event.data.get("name")
                             or "查资料")
                    self._say(f"正在{label}…")
                elif event.kind == "tool_end":
                    self._say(str(event.data.get("preview") or "整理答案…"))
                elif event.kind == "error":
                    stats["error"] = str(event.text or "")
                    stats["error_count"] += 1
                    stats["stop_reason"] = "error"
                    self.failed.emit(event.text)
                    return
                elif event.kind == "done":
                    data = event.data or {}
                    final = str(data.get("text") or "")
                    stats["usage"] = (data.get("usage")
                                      if isinstance(data.get("usage"), dict) else {})
                    stats["steps"] = int(data.get("steps") or 0)
                    stats["model_calls"] = int(data.get("model_calls") or 0)
                    stats["tool_count"] = int(data.get("tool_calls") or 0)
                    stats["stop_reason"] = str(data.get("stop_reason") or "")
                    stats["cost"] = float(data.get("cost") or 0)
                    stats["currency"] = str(data.get("currency") or "")
                    if data.get("model"):
                        stats["model"] = str(data["model"])
            if self._cancelled:
                stats["stop_reason"] = "aborted"
                return
            text = (final or "".join(parts)).strip()
            if not text:
                raise agent.AgentError("答案回来了但是空的，再问一次试试。")
            info = build_info()
            self.done.emit(text)
            if not self._deep:
                reason = answer_audit.check(text)
                if reason:
                    self.deep_suggested.emit("audit")
            write_run(info)
        except agent.AgentError as exc:
            stats["error"] = str(exc)
            stats["error_count"] += 1
            self.failed.emit(str(exc))
        except Exception as exc:                      # 兜底：别让后台异常把界面搞死
            stats["error"] = f"出错了：{exc}"
            stats["error_count"] += 1
            self.failed.emit(f"出错了：{exc}")
        finally:
            if not recorded[0]:
                write_run(build_info())


class _AnswerGrip(QtWidgets.QFrame):
    """答案面板底边的拖拽条：往下拖加高、往上拖缩矮。

    只发「相对按下时挪了多少」—— 由 AskBar 统一夹到上下限并重算窗口几何，
    面板自己有固定高度，内容再多也只滚动、不长高。
    """

    moved = QtCore.Signal(int)
    released = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("grip")
        self.setFixedHeight(GRIP_H)
        self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
        self.setToolTip("按住往下拖：答案区变高；往上拖：变矮")
        self._start = None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._start = int(event.globalPosition().y())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start is None:
            super().mouseMoveEvent(event)
            return
        self.moved.emit(int(event.globalPosition().y()) - self._start)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._start is None:
            super().mouseReleaseEvent(event)
            return
        self._start = None
        self.released.emit()
        event.accept()
