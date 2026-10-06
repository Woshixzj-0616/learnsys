"""「问谁」的接缝：把「一张图 + 一句话」交给 AI，拿回一段答案。

**直连**，不绕 agent —— 一次 HTTP 大约 2~3 秒（绕 `codex exec` 要 12 秒，差在"启动一整个 agent"）。
默认打你本机 Codex 的中转口：不用 key，但**要 Codex 开着**才在。想彻底不依赖它，
就去申请一个 key 填进 `D:/学习系统/设置.json`。

支持：
- **追问上下文**：`history` 带上同一张图的前几轮问答，AI 才知道「它」指谁。
- **流式**：`ask_stream()` 边生成边吐字，界面可以逐字往出长。
"""
from __future__ import annotations

import base64
import json
import pathlib
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator

from learnsys import config


class AskError(Exception):
    """问 AI 失败 —— 里面带一句能直接给人看的中文原因。"""


def _data_url(image_path: str | None) -> str:
    if not image_path:
        raise AskError("没拿到截图路径 —— 再框一次试试。")
    try:
        raw = pathlib.Path(image_path).read_bytes()
    except OSError as exc:
        # 截图文件可能已被「清空 / 换一张」删掉 —— 报人话，别把裸异常抛给用户
        raise AskError(f"截图读不到（{exc.strerror or exc}）—— 再框一次试试。") from exc
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _pick_text(data: dict) -> str:
    """从 Responses 的返回里把正文抠出来（形状不止一种，都兜一下）。"""
    flat = data.get("output_text")
    if isinstance(flat, str) and flat.strip():
        return flat.strip()
    chunks = []
    for item in data.get("output") or []:
        for piece in item.get("content") or []:
            if piece.get("type") in ("output_text", "text") and piece.get("text"):
                chunks.append(piece["text"])
    return "".join(chunks).strip()


def _pick_chat_text(data: dict) -> str:
    """OpenAI 兼容 /chat/completions 的返回（content 可能是整段字符串，也可能是几片）。"""
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(piece.get("text", "") for piece in content
                       if isinstance(piece, dict)).strip()
    return ""


def _trim_history(history: list | None) -> list[tuple[str, str]]:
    """只带最近几轮（旧→新），别把 token 撑爆。

    **第一轮永远保留** —— 图就挂在第一问上；把它裁掉的话，图会被错挂到后面的
    追问上（那几问本来没图），模型看到的上下文就串了。
    """
    if not history:
        return []
    turns = [(str(q), str(a)) for q, a in history if q]
    if len(turns) <= config.ASK_HISTORY_TURNS:
        return turns
    # `[turns[0]] + turns[-(N-1):]` —— N=1 时 `[-0:]` 是**全表**（Python 的坑）⇒ 单独兜
    keep_tail = config.ASK_HISTORY_TURNS - 1
    if keep_tail <= 0:
        return turns[:1]
    return [turns[0]] + turns[-keep_tail:]


_MARKDOWN_NOISE = (
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"\1"),
    (re.compile(r"__(.+?)__", re.S), r"\1"),
    (re.compile(r"(?m)^#{1,6}\s*"), ""),
    (re.compile(r"(?m)^>\s?"), ""),
    (re.compile(r"`{1,3}([^`\n]+)`{1,3}"), r"\1"),
)
_THINKING_HEADS = re.compile(
    r"(?m)^\s*\**\s*(思考|思考过程|分析|推理|内部思考|让我(先)?(看看|想一想|分析)|"
    r"Thought|Thinking|Reasoning)\s*\**\s*[:：]?\s*$"
)
_ANSWER_HEADS = re.compile(r"(?m)^\s*\**\s*(最终答案|答案|结论|回答)\s*\**\s*[:：]\s*")

_TRUNCATED_MSG = (
    "AI 没写完就被长度上限掐断了 —— 把 D:/学习系统/设置.json 里的 "
    "max_tokens 调大（默认 1500），或者把问题问小一点。")


def _is_truncated(data, style: str) -> bool:
    """这一份返回是不是**被长度上限掐断的**（两种协议都查）。

    推理模型的思考也吃 max_output_tokens —— 想完了没额度写正文，就走这儿。
    流式 Responses 的 status 在 `response` 里，非流式在顶层 —— 两处都看。
    """
    if not isinstance(data, dict):
        return False
    if style == "chat":
        try:
            return data["choices"][0].get("finish_reason") == "length"
        except (KeyError, IndexError, TypeError):
            return False
    if str(data.get("status") or "") == "incomplete":
        return True
    inner = data.get("response")
    return isinstance(inner, dict) and str(inner.get("status") or "") == "incomplete"


def tidy_answer(text: str) -> str:
    """把模型答案收拾干净：去 Markdown 花样、掐掉思考过程。"""
    if not text:
        return text
    out = text.replace("\r\n", "\n")
    # 有明确「答案：」段落 ⇒ 只留答案（思考过程整段丢掉）
    found = list(_ANSWER_HEADS.finditer(out))
    if found:
        out = out[found[-1].end():]
    # 「思考：」这类小标题行直接删
    out = _THINKING_HEADS.sub("", out)
    # 开头像铺垫（「让我看看…」「首先…」）的段落丢掉，只留后面的正文
    parts = [p.strip() for p in re.split(r"\n\s*\n", out) if p.strip()]
    while len(parts) > 1 and _looks_like_thinking(parts[0]):
        parts.pop(0)
    out = "\n\n".join(parts)
    for pattern, repl in _MARKDOWN_NOISE:
        out = pattern.sub(repl, out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def tidy_so_far(text: str) -> str:
    """流式期间用：只做**不依赖整段语义**的清洗（加粗 / 标题 / 引用 / 反引号）。

    「掐思考过程」那种要看完整段才敢下手的，留给最后的 `tidy_answer`，
    免得把还没写完的正文当成铺垫删掉。对一个增量片单独做是没用的 ——
    `**重点**` 的左右两半常被切成两片，所以调用方要拿**累积全文**来调这个。
    """
    if not text:
        return text
    out = text.replace("\r\n", "\n")
    for pattern, repl in _MARKDOWN_NOISE:
        out = pattern.sub(repl, out)
    return out


def _looks_like_thinking(paragraph: str) -> bool:
    """开头像「思考铺垫」的段落（不是答案本身）。

    要狠一点只抓口吻，**别误伤正常回答** —— 「先看题干：…答案是 42」这种就不是铺垫。
    两条都过才算：① 开头口吻对 ② 整段短（真铺垫就是一两句，正文段落通常更长）。
    """
    text = paragraph.lstrip()
    if len(text) > 40:                      # 一两句铺垫不会拖这么长 ⇒ 当正文
        return False
    if re.search(r"\d", text):              # 带数字的基本是真答案（「先看答案：42。」别删）
        return False
    first = text[:30]
    return bool(re.match(
        r"^(\*{0,2})\s*(让我|我来|我先|我需要|需要我|我们来|我试着|我打算|"
        r"先看|先分析|先观察|来看|来看看|看看这张|观察这张|分析一下|思考一下|"
        r"Looking at|Let me|First,? I|Thinking)", first))


def _system_message(style: str, with_image: bool) -> dict:
    text = config.ASK_SYSTEM_PROMPT if with_image else config.ASK_SYSTEM_PROMPT_TEXT
    if style == "chat":
        return {"role": "system", "content": text}
    return {"role": "system", "content": [{"type": "input_text", "text": text}]}


def _messages(image_path: str | None, question: str, history: list | None, style: str) -> list:
    """拼消息：图只挂在第一问上，后面的追问只带文字（省 token、够用）。没图 = 纯文字问。"""
    hist = _trim_history(history)
    image_url = _data_url(image_path) if image_path else None

    def user_first(text: str) -> dict:
        if not image_url:
            return user_text(text)
        if style == "chat":
            return {"role": "user", "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]}
        return {"role": "user", "content": [
            {"type": "input_text", "text": text},
            {"type": "input_image", "image_url": image_url},
        ]}

    def user_text(text: str) -> dict:
        if style == "chat":
            return {"role": "user", "content": [{"type": "text", "text": text}]}
        return {"role": "user", "content": [{"type": "input_text", "text": text}]}

    def assistant_text(text: str) -> dict:
        if style == "chat":
            return {"role": "assistant", "content": text}
        return {"role": "assistant", "content": [{"type": "output_text", "text": text}]}

    messages: list[dict] = [_system_message(style, with_image=bool(image_url))]
    if hist:
        first_q, first_a = hist[0]
        messages.append(user_first(first_q))
        messages.append(assistant_text(first_a))
        for q, a in hist[1:]:
            messages.append(user_text(q))
            messages.append(assistant_text(a))
        messages.append(user_text(question))
    else:
        messages.append(user_first(question))
    return messages


def _payload(image_path: str | None, question: str, history: list | None,
             style: str, stream: bool) -> tuple[dict, str]:
    messages = _messages(image_path, question, history, style)
    cap = int(getattr(config, "ASK_MAX_TOKENS", 0) or 0)
    if style == "chat":
        body = {"model": config.ASK_API_MODEL, "messages": messages}
        if cap > 0:
            body["max_tokens"] = cap
        if stream:
            body["stream"] = True
        return body, "/chat/completions"
    body = {"model": config.ASK_API_MODEL, "input": messages}
    if cap > 0:
        # 注意：推理模型的「思考过程」也吃这份配额 —— 设小了会想完没额度写正文
        body["max_output_tokens"] = cap
    if stream:
        body["stream"] = True
    return body, "/responses"


def _open(image_path: str | None, question: str, history: list | None,
          style: str, stream: bool, limit: float):
    body, path = _payload(image_path, question, history, style, stream)
    base = config.ASK_API_BASE.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if config.ASK_API_KEY:
        headers["Authorization"] = f"Bearer {config.ASK_API_KEY}"
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode("utf-8"), headers=headers
    )
    try:
        return urllib.request.urlopen(request, timeout=limit)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200].replace("\n", " ")
        raise AskError(f"AI 那边回了 {exc.code}：{detail}") from exc
    except TimeoutError as exc:
        raise AskError(f"等了 {int(limit)} 秒还没回话，先算了 —— 可以再问一次。") from exc
    except urllib.error.URLError as exc:
        raise AskError(f"连不上 {base}（{exc.reason}）—— 默认那口要 Codex 开着才在；"
                       f"自己填了 key 的话，检查一下网络和 D:/学习系统/设置.json 里的地址。") from exc
    except Exception as exc:
        raise AskError(f"出错了：{exc}") from exc


def _delta_from_chat(obj: dict) -> str:
    try:
        delta = obj["choices"][0].get("delta") or {}
    except (KeyError, IndexError, TypeError):
        return ""
    content = delta.get("content")
    if isinstance(content, str):
        return content
    return ""


def _delta_from_responses(obj: dict, want_whole: bool = False) -> str:
    """want_whole = True 才认 `response.completed` 里那份**全文**。

    实测本机中转是「先吐一堆 delta，最后再发一个 completed 带全文」——
    一律认的话，答案会被拼两遍（真出现过：77 字的答案显示成 154 字）。
    所以只有**前面一个 delta 都没吐过**时才拿它兜底。
    """
    kind = obj.get("type") or ""
    # 只要正文增量 —— reasoning / 工具调用的 delta 一律不往答案里塞（不然像「思考过程」）
    if kind in ("response.output_text.delta", "response.output_text.partial"):
        delta = obj.get("delta")
        if isinstance(delta, str):
            return delta
    if kind == "response.completed":
        if not want_whole:
            return ""
        output = obj.get("response") or obj
        text = _pick_text(output if isinstance(output, dict) else {})
        return text
    # 有的中转不带 type，直接给 delta（这时才兜底认）
    if not kind and isinstance(obj.get("delta"), str):
        return obj["delta"]
    return ""


def ask_stream(image_path: str | None, question: str, history: list | None = None,
               timeout: float | None = None,
               abort: threading.Event | None = None,
               response_sink: list | None = None) -> Iterator[str]:
    """流式问一次，边生成边 yield 文本片段。image_path=None = 纯文字问。失败抛 AskError。

    `abort`：置位后立刻收摊（不再吐字）。
    `response_sink`：把底层响应塞进去（长度为 1 的 list）—— 调用方 cancel 时可以
    `sink[0].close()` 掐断连接，不然请求会一直挂到 90 秒超时。
    """
    limit = timeout or config.ASK_TIMEOUT_SECONDS
    style = config.api_style()
    response = _open(image_path, question, history, style, stream=True, limit=limit)
    if response_sink is not None:
        response_sink.append(response)
    if abort is not None and abort.is_set():
        try:
            response.close()
        except Exception:
            pass
        return
    try:
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "event-stream" not in ctype and "stream" not in ctype:
            # 有的中转无视 stream，直接回一整段 JSON —— 当成「一次性吐完」处理
            if abort is not None and abort.is_set():
                return
            data = json.loads(response.read().decode("utf-8", "replace"))
            if _is_truncated(data, style):
                raise AskError(_TRUNCATED_MSG)
            text = _pick_chat_text(data) if style == "chat" else _pick_text(data)
            text = tidy_answer((text or "").strip())
            if text:
                yield text
            return
        emitted = False                # 已经吐出去过正文没有（决定 completed 那份全文还要不要）
        truncated = False              # 流里有没有「被掐断」的记号
        for raw in response:
            if abort is not None and abort.is_set():
                return                 # 用户掐了：已流出的字留在界面上，不再往下吐
            line = raw.decode("utf-8", "replace").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                payload = line[5:].strip()
            elif line.startswith("{"):
                payload = line
            else:
                continue
            if payload in ("[DONE]", ""):
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and _is_truncated(obj, style):
                truncated = True       # 先记下，等流里已经写出来的字都吐完再报
            piece = (_delta_from_chat(obj) if style == "chat"
                     else _delta_from_responses(obj, want_whole=not emitted))
            if piece:
                emitted = True
                yield piece
        if truncated:
            raise AskError(_TRUNCATED_MSG)   # 已流出的字还在，界面会留着 + 标一句「回答中断」
    except TimeoutError as exc:
        raise AskError(f"等了 {int(limit)} 秒还没回话，先算了 —— 可以再问一次。") from exc
    except urllib.error.URLError as exc:
        raise AskError(f"连接断了（{exc.reason}）—— 已经写出来的部分还在。") from exc
    finally:
        try:
            response.close()
        except Exception:
            pass


def ask(image_path: str | None, question: str, history: list | None = None,
        timeout: float | None = None) -> str:
    """同步问一次，拿完整答案（调用方放后台线程，别卡界面）。image_path=None = 纯文字问。"""
    limit = timeout or config.ASK_TIMEOUT_SECONDS
    style = config.api_style()
    response = _open(image_path, question, history, style, stream=False, limit=limit)
    try:
        data = json.loads(response.read().decode("utf-8", "replace"))
    except TimeoutError as exc:
        raise AskError(f"等了 {int(limit)} 秒还没回话，先算了 —— 可以再问一次。") from exc
    except Exception as exc:
        raise AskError(f"出错了：{exc}") from exc
    finally:
        try:
            response.close()
        except Exception:
            pass
    # 被长度上限掐断：模型想完了没额度写正文（推理模型的思考也吃配额）
    if _is_truncated(data, style):
        raise AskError(_TRUNCATED_MSG)
    text = _pick_chat_text(data) if style == "chat" else _pick_text(data)
    text = tidy_answer((text or "").strip())
    if not text:
        raise AskError("答案回来了但是空的，再问一次试试。")
    return text
