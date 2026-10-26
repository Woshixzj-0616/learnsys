"""看图：视觉模型优先，OCR 兜底。

DeepSeek 直连不支持图片（实测返回 [Unsupported Image]），所以这里做两段式：
1. **有视觉 key**：让视觉模型把图「忠实转述」成文字（文字/布局/箭头/关系/数字），
   主模型只看转述 —— 这样主模型不必支持图片，追问还能复用缓存；
2. **没有视觉 key / 视觉失败**：RapidOCR 只读图中文字，并明确告诉用户「没看到图」。

注意：OCR 读不到箭头、包含关系、颜色、曲线趋势。不要假装它读到了。
"""
from __future__ import annotations

import base64
import json
import pathlib
import re
import threading
import urllib.error
import urllib.request

from learnsys.agent import usage as agent_usage
from learnsys.llm.config import AgentConfig

VISION_SYSTEM = "你是图像转述器。你只做忠实转述，不回答问题、不评价、不省略。"

VISION_PROMPT = """请把这张图完整转述成文字，供另一个看不到图的模型使用。必须包括：
1. 图中所有文字：逐字转述，保留标题、编号、标点、代码/公式；
2. 版式与区域：从上到下、从左到右，各区域里有什么；
3. 结构关系：箭头方向、连线、包含/并列/因果、框与框之间的关系；
4. 图表：坐标轴、单位、趋势、关键数值；
5. 颜色/高亮：如果颜色承载了含义（例如红色表示重点），要说明。
不要回答用户可能提出的问题，只描述图本身。看不清的地方写「此处不清晰」。"""

MAX_IMAGE_BYTES = 10 * 1024 * 1024
# 模型不支持图片时有的返回 200 + 一句道歉；必须当失败处理，不能让 OCR 兜底被跳过。
UNSUPPORTED_MARKERS = (
    "无法查看这张图片", "无法处理这条消息中的图片", "图片格式不受支持",
    "unsupported image", "cannot view the image", "can't see the image",
    "can not see the image", "unable to view the image",
)
_CACHE: dict[tuple[str, int, str], str] = {}
_CACHE_MAX = 8


class VisionError(Exception):
    """视觉模型失败 —— 中文原因，调用方会退回 OCR。"""


def chat_url(base: str) -> str:
    """OpenAI 兼容的 /chat/completions 地址。

    兼容两类 base：
    - `.../v1`、`.../compatible-mode/v1`、`.../api/paas/v4` → 直接加 `/chat/completions`
    - 其它 → 加 `/v1/chat/completions`
    """
    base = (base or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if re.search(r"/v\d+$", base):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _mime(path: pathlib.Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/png"


def _data_url(path: pathlib.Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise VisionError(f"图片读不到（{exc.strerror or exc}）") from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise VisionError(f"图片太大（{len(raw) // 1024 // 1024}MB，上限 10MB）")
    return f"data:{_mime(path)};base64," + base64.b64encode(raw).decode("ascii")


def _split_data_url(value: str) -> tuple[str, str]:
    """`data:image/png;base64,xxxx` → (mime, base64)；也接受裸 base64。"""
    text = str(value or "")
    match = re.match(r"data:([^;]+);base64,(.*)$", text, re.S)
    if match:
        return match.group(1), match.group(2)
    return "image/png", text


def _anthropic_url(base: str) -> str:
    value = str(base or "").rstrip("/")
    if value.endswith("/v1"):
        return value + "/messages"
    return value + "/v1/messages"


def _thinking_off(body: dict, cfg: AgentConfig) -> dict:
    """DeepSeek 默认先思考；看图只要转述，关掉省 token、也避免正文被截断。"""
    if cfg.vision_uses_agent and "deepseek" in str(cfg.vision_base_url).lower():
        body["thinking"] = {"type": "disabled"}
    return body


def _call_vision(cfg: AgentConfig, data_url: str, timeout: float = 60.0) -> str:
    mime, b64 = _split_data_url(data_url)
    anthropic = cfg.vision_auth_style == "anthropic"
    if anthropic:
        body = _thinking_off({
            "model": cfg.vision_model,
            "max_tokens": 1600,
            "system": VISION_SYSTEM,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image", "source": {
                    "type": "base64", "media_type": mime, "data": b64}},
            ]}],
        }, cfg)
        url = _anthropic_url(cfg.vision_base_url)
        headers = {"Content-Type": "application/json",
                   "x-api-key": cfg.vision_api_key,
                   "anthropic-version": "2023-06-01"}
    else:
        body = _thinking_off({
            "model": cfg.vision_model,
            "messages": [
                {"role": "system", "content": VISION_SYSTEM},
                {"role": "user", "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
            "max_tokens": 1600,
            "temperature": 0,
        }, cfg)
        url = chat_url(cfg.vision_base_url)
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {cfg.vision_api_key}"}
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:300].replace("\n", " ")
        except Exception:
            detail = ""
        raise VisionError(f"视觉服务回了 {exc.code}" + (f"：{detail}" if detail else "")) from exc
    except TimeoutError as exc:
        raise VisionError(f"视觉服务 {int(timeout)} 秒没回话") from exc
    except urllib.error.URLError as exc:
        raise VisionError(f"连不上视觉服务（{exc.reason}）") from exc
    except Exception as exc:
        raise VisionError(f"视觉请求失败：{exc}") from exc

    try:
        data = json.loads(raw)
        if anthropic:
            blocks = data.get("content")
            text = "".join(
                str(block.get("text") or "") for block in (blocks or [])
                if isinstance(block, dict) and block.get("type") == "text")
        else:
            content = data["choices"][0]["message"]["content"]
            text = ("".join(str(p.get("text") or "") for p in content
                            if isinstance(p, dict))
                    if isinstance(content, list) else str(content or ""))
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise VisionError(f"视觉服务返回的形状不认识：{raw[:200]}") from exc
    text = text.strip()
    if not text:
        raise VisionError("视觉服务返回了空描述")
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in UNSUPPORTED_MARKERS):
        raise VisionError(
            f"视觉模型 {cfg.vision_model} 没有接受这张图：{text[:120]}")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    if usage:
        # 看图也是真实花费：记进同一本账，设置页和每日上限才看得见。
        agent_usage.record(cfg.data_root, source="vision",
                           model=cfg.vision_model, usage=usage, cfg=cfg)
    return text[:6000]


def _ocr_fallback(path: pathlib.Path) -> str:
    try:
        from learnsys.services.ocr import ocr_image
        return ocr_image(str(path)).strip()
    except Exception as exc:
        return f"（OCR 也失败了：{exc}）"


def describe_images(paths: list[str], cfg: AgentConfig,
                    abort: threading.Event | None = None) -> tuple[str, bool]:
    """把若干张图转成一段文字。返回 (描述, 是否真的用了视觉模型)。

    - 视觉可用：逐张描述，缓存命中不重复调用；
    - 视觉不可用 / 单张失败：退回 OCR，并在该图标题里注明；
    - 所有图都没有视觉：第二返回值为 False，提示词会告诉模型「你没看到图」。
    """
    unique: list[pathlib.Path] = []
    seen: set[str] = set()
    for raw in paths or []:
        if not raw:
            continue
        path = pathlib.Path(raw)
        key = str(path)
        if key in seen or not path.exists():
            continue
        seen.add(key)
        unique.append(path)
    if not unique:
        return "", False

    pieces: list[str] = []
    any_vision = False
    for index, path in enumerate(unique[:4], 1):
        if abort is not None and abort.is_set():
            break
        header = f"【图 {index}：{path.name}】"
        cache_key = (str(path), path.stat().st_mtime_ns if path.exists() else 0,
                     cfg.vision_model)
        cached = _CACHE.get(cache_key)
        if cached:
            pieces.append(header + "\n（视觉描述，缓存）\n" + cached)
            any_vision = True
            continue
        if cfg.vision_ready:
            try:
                description = _call_vision(cfg, _data_url(path))
                if len(_CACHE) >= _CACHE_MAX:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[cache_key] = description
                pieces.append(header + "\n（视觉模型转述）\n" + description)
                any_vision = True
                continue
            except VisionError as exc:
                pieces.append(header + f"\n（视觉模型没成功：{exc}；下面退回 OCR）")
        else:
            pieces.append(header + "\n（没有配置视觉模型，下面只是 OCR 文字）")
        text = _ocr_fallback(path)
        pieces.append(text if text else "（这张图没有识别到文字）")

    return "\n\n".join(pieces).strip(), any_vision
