"""Anthropic Messages 协议的流式客户端。

为什么自己写、不用 SDK：
- 只依赖标准库，打包体积和依赖都少；
- 我们要的东西很少：SSE、tool_use、thinking、中断；
- 中转口/各家兼容实现的细节（比如 `[1M]` 后缀、非标准 SSE）自己兜更稳。

协议要点：
- 请求：POST {base}/v1/messages，`stream: true`
- 事件：message_start / content_block_start / content_block_delta /
        content_block_stop / message_delta / message_stop
- 工具：assistant 消息里带 `tool_use` 块，下一轮 user 消息里带 `tool_result` 块
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from .config import AgentConfig

ANTHROPIC_VERSION = "2023-06-01"


class ProviderError(Exception):
    """模型服务失败 —— 消息是能直接给人看的中文。"""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ProviderResult:
    text: str = ""
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    content_blocks: list[dict] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: dict = field(default_factory=dict)


@dataclass
class ProviderEvent:
    kind: str                     # text / thinking / done
    text: str = ""
    result: ProviderResult | None = None


def messages_url(base: str) -> str:
    """把用户填的 base 拼成 /v1/messages（容忍结尾带不带 /v1）。"""
    base = (base or "").rstrip("/")
    if base.endswith("/messages"):
        return base
    if base.endswith("/v1"):
        return base + "/messages"
    return base + "/v1/messages"


def iter_sse(lines: Iterable) -> Iterator[tuple[str, dict]]:
    """把 SSE 行流拆成 (event 名, JSON 对象)。

    兼容三种写法：
    1. 标准 `event: xxx` + `data: {...}` + 空行；
    2. 只有 `data: {...}`，事件类型在 JSON 的 `type` 里；
    3. 直接一行一个 JSON（个别中转会这样）。
    """
    event = ""
    parts: list[str] = []

    def flush():
        nonlocal event, parts
        if not parts:
            event = ""
            return None
        payload = "\n".join(parts)
        event_name = event
        event = ""
        parts = []
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        return event_name or str(obj.get("type") or ""), obj

    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        line = line.rstrip("\r\n")
        if not line:
            item = flush()
            if item is not None:
                yield item
            continue
        if line.startswith(":"):
            continue                      # SSE 注释/心跳
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            parts.append(line[5:].strip())
        elif line.lstrip().startswith("{"):
            parts.append(line.strip())    # 非标准：直接给 JSON
    item = flush()
    if item is not None:
        yield item


def _headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "x-api-key": token,
        "anthropic-version": ANTHROPIC_VERSION,
    }


def _read_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        detail = exc.read().decode("utf-8", "replace")[:300].replace("\n", " ")
    except Exception:
        detail = ""
    return f"模型服务回了 {exc.code}" + (f"：{detail}" if detail else "")


def _is_deepseek(base: str) -> bool:
    return "deepseek" in str(base or "").lower()


def _body(cfg: AgentConfig, system: str, messages: list, tools: list | None, stream: bool) -> dict:
    body = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "system": system,
        "messages": messages,
        "stream": stream,
    }
    # DeepSeek 的 Anthropic 兼容口默认 **开启** 思考；不显式发这个参数，
    # 设置页里的「思考模式」就是个摆设（曾经确实是）。budget_tokens 在 DeepSeek
    # 被忽略，所以只发 type。其它服务商保持原行为，避免不认识这个字段的中转直接 400。
    if _is_deepseek(cfg.base_url):
        body["thinking"] = {"type": "enabled" if cfg.thinking else "disabled"}
    if tools:
        body["tools"] = tools
    return body


def _blocks_from_json(data: dict) -> ProviderResult:
    """非流式返回（有的中转无视 stream）→ 统一成 ProviderResult。"""
    blocks: list[dict] = []
    tool_calls: list[ToolCall] = []
    texts: list[str] = []
    thinking: list[str] = []
    for item in data.get("content") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            text = str(item.get("text") or "")
            texts.append(text)
            blocks.append({"type": "text", "text": text})
        elif kind == "thinking":
            thought = str(item.get("thinking") or "")
            thinking.append(thought)
            block = {"type": "thinking", "thinking": thought}
            if item.get("signature"):
                block["signature"] = item["signature"]
            blocks.append(block)
        elif kind == "tool_use":
            call = ToolCall(str(item.get("id") or ""), str(item.get("name") or ""),
                            item.get("input") if isinstance(item.get("input"), dict) else {})
            tool_calls.append(call)
            blocks.append({"type": "tool_use", "id": call.id, "name": call.name,
                           "input": call.input})
    return ProviderResult(
        text="".join(texts).strip(),
        thinking="".join(thinking),
        tool_calls=tool_calls,
        content_blocks=blocks,
        stop_reason=str(data.get("stop_reason") or ("tool_use" if tool_calls else "end_turn")),
        usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
    )


def stream_messages(cfg: AgentConfig, system: str, messages: list,
                    tools: list | None = None, *,
                    abort: threading.Event | None = None,
                    response_sink: list | None = None,
                    timeout: float = 90.0) -> Iterator[ProviderEvent]:
    """流式跑一轮，边出字边 yield。工具调用在最后的 done 里一次性给出。"""
    if abort is not None and abort.is_set():
        yield ProviderEvent("done", result=ProviderResult(stop_reason="aborted"))
        return
    if not cfg.ready:
        raise ProviderError("还没配置模型 —— 打开设置，填 API 地址和密钥。")

    request = urllib.request.Request(
        messages_url(cfg.base_url),
        data=json.dumps(_body(cfg, system, messages, tools, True)).encode("utf-8"),
        headers=_headers(cfg.auth_token),
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise ProviderError(_read_http_error(exc)) from exc
    except TimeoutError as exc:
        raise ProviderError(f"等了 {int(timeout)} 秒还没连上模型服务，稍后再试。") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"连不上模型服务（{exc.reason}）—— 检查网络和设置里的地址。") from exc
    except Exception as exc:
        raise ProviderError(f"请求模型失败：{exc}") from exc

    if response_sink is not None:
        response_sink.append(response)     # 调用方可 close() 掐断，不用等超时

    try:
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "event-stream" not in ctype and "stream" not in ctype:
            raw = response.read().decode("utf-8", "replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ProviderError(f"模型返回的不是 JSON：{raw[:200]}") from exc
            result = _blocks_from_json(data)
            for block in result.content_blocks:
                if block.get("type") == "text" and block.get("text"):
                    yield ProviderEvent("text", str(block["text"]))
            yield ProviderEvent("done", result=result)
            return

        blocks: dict[int, dict] = {}
        stop_reason = ""
        usage: dict = {}

        def state_at(index: int) -> dict:
            state = blocks.get(index)
            if state is None:
                state = {"type": "", "text": "", "thinking": "", "signature": "",
                         "id": "", "name": "", "input_json": "", "input": {}}
                blocks[index] = state
            return state

        for event_name, obj in iter_sse(response):
            if abort is not None and abort.is_set():
                break
            kind = event_name or str(obj.get("type") or "")
            if kind == "error":
                error = obj.get("error") if isinstance(obj.get("error"), dict) else {}
                raise ProviderError(str(error.get("message") or "模型服务报错"))
            if kind == "message_start":
                message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
                if isinstance(message.get("usage"), dict):
                    usage.update(message["usage"])
                continue
            if kind == "content_block_start":
                index = int(obj.get("index") or 0)
                block = obj.get("content_block") if isinstance(obj.get("content_block"), dict) else {}
                state = state_at(index)
                state["type"] = str(block.get("type") or "")
                state["text"] = str(block.get("text") or "")
                state["thinking"] = str(block.get("thinking") or "")
                state["signature"] = str(block.get("signature") or "")
                state["id"] = str(block.get("id") or "")
                state["name"] = str(block.get("name") or "")
                if isinstance(block.get("input"), dict):
                    state["input"] = block["input"]
                continue
            if kind == "content_block_delta":
                index = int(obj.get("index") or 0)
                delta = obj.get("delta") if isinstance(obj.get("delta"), dict) else {}
                dtype = str(delta.get("type") or "")
                state = state_at(index)
                if dtype == "text_delta":
                    piece = str(delta.get("text") or "")
                    if piece:
                        state["text"] += piece
                        yield ProviderEvent("text", piece)
                elif dtype == "thinking_delta":
                    piece = str(delta.get("thinking") or "")
                    if piece:
                        state["thinking"] += piece
                        yield ProviderEvent("thinking", piece)
                elif dtype == "signature_delta":
                    state["signature"] += str(delta.get("signature") or "")
                elif dtype == "input_json_delta":
                    state["input_json"] += str(delta.get("partial_json") or "")
                continue
            if kind == "message_delta":
                delta = obj.get("delta") if isinstance(obj.get("delta"), dict) else {}
                if delta.get("stop_reason"):
                    stop_reason = str(delta["stop_reason"])
                if isinstance(obj.get("usage"), dict):
                    usage.update(obj["usage"])
                continue
            if kind == "message_stop":
                break

        if abort is not None and abort.is_set():
            # 已经吐出去的字保留；stop_reason 标 aborted，上层不再当完成
            stop_reason = "aborted"

        result = _result_from_blocks(blocks, stop_reason, usage)
        yield ProviderEvent("done", result=result)
    except TimeoutError as exc:
        raise ProviderError(f"模型服务 {int(timeout)} 秒没回话，先算了 —— 可以重试。") from exc
    except urllib.error.URLError as exc:
        if abort is not None and abort.is_set():
            yield ProviderEvent("done", result=ProviderResult(stop_reason="aborted"))
            return
        raise ProviderError(f"连接断了（{exc.reason}）—— 已经写出来的部分还在。") from exc
    except (ValueError, OSError) as exc:
        # 被 cancel() 关掉响应时，读流会抛 ValueError/OSError —— 当主动中断处理
        if abort is not None and abort.is_set():
            yield ProviderEvent("done", result=ProviderResult(stop_reason="aborted"))
            return
        raise ProviderError(f"读模型返回时断了：{exc}") from exc
    finally:
        try:
            response.close()
        except Exception:
            pass


def _result_from_blocks(blocks: dict[int, dict], stop_reason: str,
                        usage: dict) -> ProviderResult:
    """把流式攒下的块整理成最终结果 + 可回传的 content_blocks。"""
    ordered = [blocks[i] for i in sorted(blocks)]
    content: list[dict] = []
    tool_calls: list[ToolCall] = []
    texts: list[str] = []
    thinking: list[str] = []

    for state in ordered:
        kind = state.get("type")
        if kind == "text":
            text = state.get("text") or ""
            if not text:
                continue
            texts.append(text)
            content.append({"type": "text", "text": text})
        elif kind == "thinking":
            thought = state.get("thinking") or ""
            if not thought:
                continue
            thinking.append(thought)
            block = {"type": "thinking", "thinking": thought}
            if state.get("signature"):
                block["signature"] = state["signature"]
            content.append(block)
        elif kind == "tool_use":
            raw = state.get("input_json") or ""
            args = state.get("input") if isinstance(state.get("input"), dict) else {}
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        args = parsed
                except json.JSONDecodeError:
                    pass                       # 参数坏了：让工具自己报缺参数，别炸整轮
            call = ToolCall(str(state.get("id") or ""), str(state.get("name") or ""), args)
            tool_calls.append(call)
            content.append({"type": "tool_use", "id": call.id, "name": call.name,
                            "input": call.input})

    return ProviderResult(
        text="".join(texts).strip(),
        thinking="".join(thinking),
        tool_calls=tool_calls,
        content_blocks=content,
        stop_reason=stop_reason or ("tool_use" if tool_calls else "end_turn"),
        usage=usage,
    )
