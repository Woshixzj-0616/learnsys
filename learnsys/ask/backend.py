"""「问谁」的接缝：把「一张图 + 一句话」交给 AI，拿回一段答案。

**直连**，不绕 agent —— 一次 HTTP 大约 2~3 秒（绕 `codex exec` 要 12 秒，差在"启动一整个 agent"）。
默认打你本机 Codex 的中转口：不用 key，但**要 Codex 开着**才在。想彻底不依赖它，
就去申请一个 DeepSeek key 填进 `config.ASK_API_KEY`。
"""
from __future__ import annotations

import base64
import json
import pathlib
import urllib.error
import urllib.request

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


def ask(image_path: str, question: str, timeout: float | None = None) -> str:
    """同步问一次（调用方放后台线程，别卡界面）。失败抛 AskError。"""
    limit = timeout or config.ASK_TIMEOUT_SECONDS
    base = config.ASK_API_BASE.rstrip("/")
    style = config.api_style()
    if style == "chat":
        # 自己填了 key 的（硅基流动 / 智谱 / 通义千问…）：OpenAI 兼容那套写法
        payload = {
            "model": config.ASK_API_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": _data_url(image_path)}},
                ],
            }],
        }
        path = "/chat/completions"
    else:
        payload = {
            "model": config.ASK_API_MODEL,
            "input": [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": question},
                    {"type": "input_image", "image_url": _data_url(image_path)},
                ],
            }],
        }
        path = "/responses"
    headers = {"Content-Type": "application/json"}
    if config.ASK_API_KEY:
        headers["Authorization"] = f"Bearer {config.ASK_API_KEY}"
    request = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=limit) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200].replace("\n", " ")
        raise AskError(f"AI 那边回了 {exc.code}：{detail}")
    except TimeoutError:
        raise AskError(f"等了 {int(limit)} 秒还没回话，先算了 —— 可以再问一次。")
    except urllib.error.URLError as exc:
        raise AskError(f"连不上 {base}（{exc.reason}）—— 默认那口要 Codex 开着才在；"
                       f"自己填了 key 的话，检查一下网络和 D:/学习系统/设置.json 里的地址。")
    except Exception as exc:
        raise AskError(f"出错了：{exc}")
    text = _pick_chat_text(data) if style == "chat" else _pick_text(data)
    if not text:
        raise AskError("答案回来了但是空的，再问一次试试。")
    return text
