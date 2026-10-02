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
import urllib.error
import urllib.request
from collections.abc import Iterator

from learnsys import config


class AskError(Exception):
    """问 AI 失败 —— 里面带一句能直接给人看的中文原因。"""


def _data_url(image_path: str) -> str:
    raw = pathlib.Path(image_path).read_bytes()
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
    """只带最近几轮（旧→新），别把 token 撑爆。"""
    if not history:
        return []
    turns = [(str(q), str(a)) for q, a in history if q]
    return turns[-config.ASK_HISTORY_TURNS:]


def _messages(image_path: str, question: str, history: list | None, style: str) -> list:
    """拼消息：图只挂在第一问上，后面的追问只带文字（省 token、够用）。"""
    hist = _trim_history(history)
    image_url = _data_url(image_path)

    def user_first(text: str) -> dict:
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

    messages: list[dict] = []
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


def _payload(image_path: str, question: str, history: list | None,
             style: str, stream: bool) -> tuple[dict, str]:
    messages = _messages(image_path, question, history, style)
    if style == "chat":
        body = {"model": config.ASK_API_MODEL, "messages": messages}
        if stream:
            body["stream"] = True
        return body, "/chat/completions"
    body = {"model": config.ASK_API_MODEL, "input": messages}
    if stream:
        body["stream"] = True
    return body, "/responses"


def _open(image_path: str, question: str, history: list | None,
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


def _delta_from_responses(obj: dict) -> str:
    kind = obj.get("type") or ""
    if kind in ("response.output_text.delta", "response.output_text.partial"):
        delta = obj.get("delta")
        if isinstance(delta, str):
            return delta
    if kind == "response.completed":
        output = obj.get("response") or obj
        text = _pick_text(output if isinstance(output, dict) else {})
        return text
    # 有的中转不带 type，直接给 delta
    delta = obj.get("delta")
    if isinstance(delta, str):
        return delta
    return ""


def ask_stream(image_path: str, question: str, history: list | None = None,
               timeout: float | None = None) -> Iterator[str]:
    """流式问一次，边生成边 yield 文本片段。失败抛 AskError（可能已吐出一部分）。"""
    limit = timeout or config.ASK_TIMEOUT_SECONDS
    style = config.api_style()
    response = _open(image_path, question, history, style, stream=True, limit=limit)
    try:
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "event-stream" not in ctype and "stream" not in ctype:
            # 有的中转无视 stream，直接回一整段 JSON —— 当成「一次性吐完」处理
            data = json.loads(response.read().decode("utf-8", "replace"))
            text = _pick_chat_text(data) if style == "chat" else _pick_text(data)
            text = (text or "").strip()
            if text:
                yield text
            return
        for raw in response:
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
            piece = _delta_from_chat(obj) if style == "chat" else _delta_from_responses(obj)
            if piece:
                yield piece
    except TimeoutError as exc:
        raise AskError(f"等了 {int(limit)} 秒还没回话，先算了 —— 可以再问一次。") from exc
    except urllib.error.URLError as exc:
        raise AskError(f"连接断了（{exc.reason}）—— 已经写出来的部分还在。") from exc
    finally:
        try:
            response.close()
        except Exception:
            pass


def ask(image_path: str, question: str, history: list | None = None,
        timeout: float | None = None) -> str:
    """同步问一次，拿完整答案（调用方放后台线程，别卡界面）。失败抛 AskError。"""
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
    text = _pick_chat_text(data) if style == "chat" else _pick_text(data)
    text = (text or "").strip()
    if not text:
        raise AskError("答案回来了但是空的，再问一次试试。")
    return text
