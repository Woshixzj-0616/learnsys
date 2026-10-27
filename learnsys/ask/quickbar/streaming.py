"""一轮问答：提问上屏、流式回调、渐进渲染、自检/确认展示、收尾。"""
from __future__ import annotations

import functools
import html as html_mod
import time
import uuid

from PySide6 import QtCore, QtGui, QtWidgets

from ..qt import style
from ..qt import tokens as token_source
from .common import (STATE_DONE, STATE_ERROR, STATE_HISTORY, STATE_STREAMING,
                     STATE_THINKING, _STREAM_RENDER_SECONDS, _SCROLL_SLACK,
                     _answer_char, _ask_char, _gap_block, _markdown_bold_for_qt)
from .workers import _AskWorker


@functools.lru_cache(maxsize=1)
def _tokens() -> dict[str, str]:
    """`tokens.css` 不会在进程里变；缓存一份，避免每帧都读文件。"""
    return token_source.merged(token_source.read_web_tokens())


def _hex(name: str, fallback: str = "#000000") -> str:
    """令牌 → QTextDocument 能吃的 `#rrggbb`。"""
    return style.color(_tokens().get(name) or fallback).name()


class StreamMixin:
    def _start_turn(self, question: str) -> None:
        """把问题先上屏 —— **淡蓝底、只包住文字的那一块是你的话**，下面空一行才是 AI 的回答。

        新一轮（还没写过 / 刚清空 / 刚开新会话）就先清掉旧的；
        追问就接在上一轮答案后面写，像聊天记录一样往下长。
        """
        if self._render_timer.isActive():
            self._render_timer.stop()         # 上一轮排的帧不许写进这一轮
        if self._answer_start is None:
            self.answer.clear()
            self._showing_history = False     # 新问起手，历史视图已经不在了
        cursor = self.answer.textCursor()
        if self.answer.toPlainText().strip():
            cursor.movePosition(QtGui.QTextCursor.End)
            cursor.insertBlock(_gap_block())      # 上一轮和这一轮之间空一行
        else:
            cursor.movePosition(QtGui.QTextCursor.Start)
        # 前后各一个空格 = 色块的内边距（Qt 富文本没有 padding，只能这样）
        cursor.insertText(f" {question} ", _ask_char())
        cursor.insertBlock(_gap_block(), _answer_char())   # 空一行
        cursor.insertBlock(_gap_block(), _answer_char())   # AI 的回答写在这一块
        self._answer_start = cursor.position()
        self._last_answer = ""     # 每一轮的答案区都是从头算的 —— 不清的话，流式期间
                                   # 复制会把上一轮答案拼进来，中断时上下文也会被污染
        self._stream_text = ""
        self._thinking_text = ""
        self._last_thinking = ""
        self._answer_view = "answer"
        self._view_pinned = False
        self._last_render_at = 0.0
        self._follow = True        # 新一轮从跟随最新内容开始（用户上翻就停，见 _on_chunk）
        cursor.setCharFormat(_answer_char())     # 答案用正常颜色，别接着用蓝底那块的白字
        self.answer.setTextCursor(cursor)
        self._scroll_follow()
        self.set_state(STATE_THINKING)     # 面板显隐只走状态机（这里只是把面板亮出来）

    def submit(self) -> None:
        if self._worker is not None:
            # 别闷声不响地吞掉这一次回车 —— 不然用户只看到「按了没反应」
            self.show_message("上一句还在写 —— 等它写完，或者点「新会话」重开一轮。")
            return
        question = self.ask.text().strip()
        if not question:
            self.ask.setFocus()
            self.show_message("先打个问题（框不框选都行 —— 框了就问那块屏，不框就是纯文字问）。")
            return
        if question.startswith(">"):  # 电脑助手：> 后面是要 AI 帮忙操作电脑的事
            self.computer_request.emit(question[1:].strip())
            self.ask.clear()
            return
        send_text = question
        if self.doc_path:             # 挂了课件：正文随问题一起发
            send_text = f"【参考文档：{self.doc_name}】\n{self.doc_text}\n\n【问题】{question}"
        # 记录开着的时候，把最近几分钟的课堂转写捎给 AI ——「这题老师怎么讲的来着」才答得上
        context = ""
        if self.extra_context_provider is not None:
            try:
                context = self.extra_context_provider() or ""
            except Exception:
                context = ""                 # 上下文拿不到就纯问，别拦着用户
        self._begin_turn(send_text, question, context)
        self.ask.clear()              # 问题已经上屏了 ⇒ 输入框清空，直接打下一句

    def ask_with_context(self, send_text: str, display_text: str, context: str = "",
                         images: list[str] | None = None, mode: str = "",
                         system_override: str = "", use_tools: bool = True) -> None:
        """「程序替用户问」的入口（复盘/测验/电脑助手用）：界面显示 display_text，发给 AI 的是 send_text。

        images = 附加截图（多图），主 image_path 之外最多再带 4 张。
        system_override / use_tools 给非导师任务（比如电脑助手只出 JSON 计划）。
        """
        if self._worker is not None:
            self.show_message("上一句还在写 —— 等它写完再点。")
            return
        if not send_text.strip():
            return
        self._begin_turn(send_text, display_text, context, images, mode,
                         system_override, use_tools)

    def show_recording_result(self, text: str, session_id: int = 0) -> None:
        """停止录像后的汇总卡：写进答案区，带「打开录像页」深链。

        不进入问答历史；下一次提问就是一轮新对话。
        """
        self._drop_running()
        self._turns = []
        self._thread = uuid.uuid4().hex[:12]
        self._reset_answer()
        self._start_turn("录像完成")
        link = (f"#/recordings?session={int(session_id)}" if session_id
                else "#/recordings")
        body = (text or "").strip()
        self._set_answer_markdown(f"{body}\n\n[打开录像页]({link})")
        self.set_state(STATE_DONE, status="录像完成 —— 点链接打开录像页，或继续提问")
        self.ask.setFocus()

    def _begin_turn(self, send_text: str, display_text: str, context: str,
                    images: list[str] | None = None, mode: str = "",
                    system_override: str = "", use_tools: bool = True) -> None:
        """开一轮问答：显示 display_text，问 AI 的是 send_text（可带转写上下文）。"""
        self._started_at = time.monotonic()
        self._dots = 0
        self._streaming = False
        self._activity = ""
        self._start_turn(display_text)
        self.set_state(STATE_THINKING, status="在想…")
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(400)
        self._turn_seq += 1           # 开新的一轮：旧的（被掐掉的）回来时靠这个号认出来
        seq = self._turn_seq
        # 这一轮的图/文身份**当场拍死**：答案回来时界面可能已经换过图、甚至清过空，
        # 再读 self._image_path 会把图问答错记成纯文字、连归档截图都丢掉。
        kind = "image" if self._image_path else "text"
        image_path = self._image_path or ""
        self._worker = _AskWorker(self._image_path, send_text, list(self._turns), self,
                                  context=context, extra_images=images)
        # 模式用属性给，不放进构造参数：旧测试里替换的 FakeWorker 只认旧签名，
        # 传 `mode=` 会直接 TypeError。属性赋值对新旧 worker 都无害。
        self._worker._mode = mode or ("quiz" if self.quiz_mode else self.ask_mode)
        self._worker._system_override = system_override
        self._worker._use_tools = use_tools
        self._worker._conversation_key = self._thread
        self._workers.append(self._worker)       # 留着，退出时要 wait（shutdown）
        self._worker.finished.connect(self._reap_workers)
        if hasattr(self._worker, "activity"):
            self._worker.activity.connect(self._on_activity)
        if hasattr(self._worker, "confirm_needed"):
            self._worker.confirm_needed.connect(self._on_confirm_write)
        self._worker.chunk.connect(lambda piece, replace, s=seq: self._on_chunk(piece, replace, s))
        if hasattr(self._worker, "thinking"):
            self._worker.thinking.connect(lambda piece, s=seq: self._on_thinking(piece, s))
        self._worker.done.connect(
            lambda text, s=seq, k=kind, p=image_path: self._finish(display_text, text, None, s, k, p))
        self._worker.failed.connect(
            lambda message, s=seq, k=kind, p=image_path: self._finish(display_text, "", message, s, k, p))
        self._worker.start()

    def _on_activity(self, text: str) -> None:
        """后台线程发来的一句话：看图 / 查记录 / 推理中。只更新状态行，不动布局。"""
        self._activity = str(text or "")

    def _on_confirm_write(self, payload) -> None:
        """写操作确认：横栏弹一个原生对话框；后台线程正卡在同一个 slot 上等。"""
        payload = payload if isinstance(payload, dict) else {}
        summary = str(payload.get("summary") or "这次写入")
        answer = QtWidgets.QMessageBox.question(
            self, "需要你确认", f"{summary}\n\n允许这次写入吗？",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        worker = self._worker
        slot = getattr(worker, "_confirm_slot", None) if worker is not None else None
        if isinstance(slot, dict):
            slot["ok"] = answer == QtWidgets.QMessageBox.StandardButton.Yes
            slot["event"].set()

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        # 有更具体的动作（查记录 / 看图）就显示它；否则按「先想后写」显示
        label = self._activity or ("正在写" if self._streaming else "在想")
        self._set_status(label + "·" * self._dots
                         + f"  {time.monotonic() - self._started_at:.0f} 秒")

    def _on_chunk(self, piece: str, replace: bool = False, seq: int = 0) -> None:
        """流式正文：先攒原文，再按 8 帧/秒重排 Markdown。

        以前是「逐字 insertText，最后一次性 setMarkdown」—— 用户会先看到满屏 `**`、
        `##`，等结束再突然变格式。现在每一帧看到的都是渲染后的样子。
        `seq` 是这一轮的号 —— 被掐掉的旧轮（清空/新会话/换图）流回来的碎片一律不进界面。
        """
        if seq != self._turn_seq:
            return
        if self._state_name != STATE_STREAMING:
            self.set_state(STATE_STREAMING)     # 只切一次：thinking → streaming 不动几何
        # 插入**之前**看一眼滚动条：用户在底部 = 还在跟着看；上翻过 = 别拽人
        sb = self.answer.verticalScrollBar()
        self._follow = sb.value() >= sb.maximum() - _SCROLL_SLACK
        self._streaming = True
        self._set_copy_enabled(True)
        if replace:
            self._stream_text = piece
            self._last_answer = piece
        else:
            self._stream_text += piece
            self._last_answer += piece
        # 正文来了：自动从「思考」切回「答案」，但用户手动点过就尊重他的选择
        if not self._view_pinned:
            self._answer_view = "answer"
        self._schedule_render()

    def _on_thinking(self, piece: str, seq: int = 0) -> None:
        """思考增量：横栏也能看见推理在推进，而不是只有一个「在想」。"""
        if seq != self._turn_seq or not piece:
            return
        if self._state_name not in (STATE_THINKING, STATE_STREAMING):
            return                              # 已经 done/error 的迟到碎片不要
        self._thinking_text += piece
        if not self._view_pinned and not self._stream_text:
            self._answer_view = "thinking"
        self._schedule_render()

    def _schedule_render(self) -> None:
        """合并短时间内的很多 chunk，只排一次重排。"""
        if self._render_timer.isActive():
            return
        wait = max(0.0, _STREAM_RENDER_SECONDS - (time.monotonic() - self._last_render_at))
        self._render_timer.start(max(1, int(wait * 1000)))

    def _flush_stream_render(self) -> None:
        if self._state_name not in (STATE_THINKING, STATE_STREAMING):
            return
        self._render_answer_view()
        self._last_render_at = time.monotonic()

    def _header_link(self, target: str, label: str) -> str:
        return ('<p style="margin:0 0 6px 0">'
                f'<a href="think:{target}" style="color:{_hex("--accent-strong")};'
                'text-decoration:none">'
                f'{html_mod.escape(label)}</a></p>')

    def _thinking_html(self) -> str:
        body = html_mod.escape(self._thinking_text or "（这一轮没有思考过程）")
        body = body.replace("\n", "<br>")
        return (f'<div style="color:{_hex("--text-dim")};font-size:14px;line-height:1.55">'
                + body + "</div>")

    def _render_answer_view(self) -> None:
        """把「答案」那一段换成当前视图（答案 Markdown / 思考过程）。

        只动答案段，上面的问题气泡不动；面板高度固定，窗口几何不变。
        """
        if self._answer_start is None:
            return
        sb = self.answer.verticalScrollBar()
        value = sb.value()
        follow = self._follow
        cursor = self.answer.textCursor()
        cursor.setPosition(self._answer_start)
        cursor.movePosition(QtGui.QTextCursor.End, QtGui.QTextCursor.KeepAnchor)
        if self._answer_view == "thinking":
            cursor.insertHtml(self._header_link("answer", "← 回到答案"))
            cursor.insertHtml(self._thinking_html())
        else:
            if self._thinking_text.strip():
                cursor.insertHtml(self._header_link(
                    "thinking", f"💭 查看思考过程（{len(self._thinking_text)} 字）"))
            document = QtGui.QTextDocument()
            # Qt 的 toHtml() 会按文档默认字体写死 font-size；不设就会从 15px 缩回 9pt。
            font = QtGui.QFont("Microsoft YaHei UI")
            font.setPixelSize(15)
            document.setDefaultFont(font)
            document.setDocumentMargin(0)
            document.setDefaultStyleSheet(
                f"body {{ color: {_hex('--text')}; }}"
                f"h1,h2,h3,h4 {{ color: {_hex('--text')}; }}"
                f"code, pre {{ color: {_hex('--mark')}; "
                "font-family: 'Cascadia Mono','Consolas',monospace; }"
                f"a {{ color: {_hex('--accent-strong')}; }}"
                f"blockquote {{ color: {_hex('--text-dim')}; }}"
            )
            document.setMarkdown(_markdown_bold_for_qt(self._stream_text))
            cursor.insertHtml(document.toHtml())
            if self._thinking_text.strip():
                # 流式时视图跟着底部走，顶部的开关会滚出屏幕 —— 底部再放一个
                cursor.insertHtml(self._header_link(
                    "thinking", f"💭 查看思考过程（{len(self._thinking_text)} 字）"))
        if follow:
            sb.setValue(sb.maximum())
        else:
            sb.setValue(min(value, sb.maximum()))
        self._set_copy_enabled(bool(self._last_answer.strip()))

    def _on_answer_anchor(self, url: QtCore.QUrl) -> None:
        text = url.toString()
        if text.startswith("think:"):
            target = text.split(":", 1)[1]
            if target in ("answer", "thinking"):
                self._answer_view = target
                self._view_pinned = True
                self._render_answer_view()
            return
        if text.startswith("#/"):
            self.open_link_requested.emit(text)   # 屏内深链 → 交给 app 打开工作台页面
            return
        if url.scheme() in ("http", "https"):
            QtGui.QDesktopServices.openUrl(url)

    def _set_answer_part(self, text: str) -> None:
        """只替换「答案」那一段 —— 「我：」那一行留在上面不动。"""
        if self._answer_start is None:
            return
        self._stream_text = text
        self._last_answer = text
        self._render_answer_view()

    def _set_answer_markdown(self, text: str) -> None:
        """兼容旧调用：把答案段按 Markdown 重排一次。"""
        self._stream_text = text
        self._last_answer = text
        if not self._view_pinned:
            self._answer_view = "answer"
        self._render_answer_view()

    def _finish(self, question: str, text: str, error, seq: int = 0,
                kind: str = "text", image_path: str = "") -> None:
        # 被掐掉的旧那一轮（用户已经开了新会话 / 清空）跑完也会走到这儿 ——
        # 不挡住的话，旧答案会写在新界面上，看起来就像「新会话没生效、还多出一份」。
        # ⚠️ 别用 sender() 判断：信号是经 lambda 连的，PySide6 里拿不到发送者，
        # 判断会一直失败 ⇒ `_finish` 整个被跳过 ⇒ 计时器不停、按钮不恢复（真踩过）。
        # `kind` / `image_path` 是 submit 当场拍死的，不看现在的 self._image_path ——
        # 中途点 ✕ / 清空会把图丢掉，再读就会把图问答错记成纯文字。
        if seq != self._turn_seq:
            return
        self._activity = ""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._worker = None
        self._streaming = False
        ms = int((time.monotonic() - self._started_at) * 1000)
        if error:
            # 只看「答案那一段」有没有写出来的 —— 上面那行「我：」不算
            partial = self._last_answer.strip()
            if partial:
                # 流到一半断了：留着已写出的，底下标一句
                self._last_thinking = self._thinking_text
                if not self._view_pinned:
                    self._answer_view = "answer"
                self._render_answer_view()
                self.set_state(STATE_ERROR, status=f"回答中断 —— {error}")
                # 已写出的那段也算上下文 —— 不然追问「继续」时 AI 记不得自己说过啥
                self._turns.append((question, partial))
            else:
                self._set_answer_part(error)
                self.set_state(STATE_ERROR, status="没成功 —— 改一下再问")
        else:
            self._stream_text = text
            self._last_thinking = self._thinking_text
            if not self._view_pinned:
                self._answer_view = "answer"
            self._set_answer_markdown(text)      # 最后一帧：保证完整答案用 Markdown 渲染
            self._turns.append((question, text))
            if kind == "image":
                status = f"用了 {ms / 1000:.1f} 秒 · 还想追问就直接再打字（看的还是这张图）"
            else:
                status = f"用了 {ms / 1000:.1f} 秒 · 还想追问就直接再打字"
            self.set_state(STATE_DONE, status=status)
            self.answered.emit({
                "question": question,
                "answer": text,
                "ms": ms,
                "kind": kind,
                "image_path": image_path,
                "thread": self._thread,
            })
        self._scroll_follow()
        self.ask.setFocus(QtCore.Qt.OtherFocusReason)
