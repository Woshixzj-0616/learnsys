"""后台线程：问答流、占用统计、答案底边拖拽条。"""
from __future__ import annotations

import threading

from PySide6 import QtCore, QtWidgets

from learnsys import agent
from learnsys.agent import tools as agent_tools
from learnsys.ask import usage
from .common import GRIP_H


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
        self._conversation_key = ""    # 同一轮对话的稳定号，测验收错题去重用
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
        try:
            request = agent.AgentRequest(
                message=self._question,
                history=self._history,
                image_path=self._image_path,
                extra_images=self._extra_images,
                context=self._context,
                mode=self._mode,
                system_override=self._system_override,
                use_tools=self._use_tools,
                conversation_key=self._conversation_key,
            )
            for event in agent.run(request, abort=self._abort, response_sink=self._sink,
                                   confirm=self._confirm_write):
                if self._cancelled:
                    return
                if event.kind == "text":
                    parts.append(event.text)
                    self.chunk.emit(event.text, False)
                elif event.kind == "thinking":
                    self._say("正在推理…")
                    if event.text:
                        self.thinking.emit(event.text)
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
                    name = event.data.get("name") or "记录"
                    self._say(f"查找：{name}…")
                elif event.kind == "tool_end":
                    self._say(str(event.data.get("preview") or "整理答案…"))
                elif event.kind == "error":
                    self.failed.emit(event.text)
                    return
                elif event.kind == "done":
                    final = str(event.data.get("text") or "")
            if self._cancelled:
                return
            text = (final or "".join(parts)).strip()
            if not text:
                raise agent.AgentError("答案回来了但是空的，再问一次试试。")
            self.done.emit(text)
        except agent.AgentError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                      # 兜底：别让后台异常把界面搞死
            self.failed.emit(f"出错了：{exc}")


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
