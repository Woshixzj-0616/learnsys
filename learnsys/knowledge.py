"""知识点类目与提示词规则（零依赖）。

只放常量、归一和提示词文本，供 `ask/`、`agent/`、`services/` 共用；
不要在这里碰数据库或 FastAPI。
"""
from __future__ import annotations

import re

CATEGORIES = (
    {"name": "词汇", "kind": "vocab", "sort": 10},
    {"name": "语音", "kind": "phonetics", "sort": 20},
    {"name": "语法", "kind": "grammar", "sort": 30},
    {"name": "听力细节", "kind": "listening_detail", "sort": 40},
    {"name": "听力主旨", "kind": "listening_main", "sort": 50},
    {"name": "听力推断", "kind": "listening_inference", "sort": 60},
    {"name": "阅读", "kind": "reading", "sort": 70},
    {"name": "其他", "kind": "other", "sort": 999},
)
CATEGORY_NAMES = tuple(item["name"] for item in CATEGORIES)

# 旧数据 / 模型偶尔跑偏时的同义词；只做保守归并，不猜。
ALIASES = {
    "生词": "词汇", "单词": "词汇", "词汇量": "词汇",
    "连读": "语音", "发音": "语音", "听音": "语音", "语音辨识": "语音",
    "句法": "语法", "从句": "语法", "时态": "语法", "非谓语": "语法",
    "细节": "听力细节", "听力": "听力细节", "细节理解": "听力细节",
    "主旨": "听力主旨", "大意": "听力主旨", "中心思想": "听力主旨",
    "推断": "听力推断", "推理": "听力推断", "态度": "听力推断",
    "阅读细节": "阅读", "阅读理解": "阅读",
}

_SPLIT_RE = re.compile(r"[、,，;；\n]+")


def normalize_points(raw) -> tuple[list[str], str]:
    """把模型/旧 tags 的原始 token 归一到 8 类目。

    返回 `(names, source)`：source 为 `model` 表示至少识别出一个真实类目；
    `fallback` 表示一个都没识别，落到「其他」，不能计入 BKT 样本。
    """
    if isinstance(raw, str):
        tokens = _SPLIT_RE.split(raw.replace("\r", ""))
    elif isinstance(raw, (list, tuple, set)):
        tokens = []
        for item in raw:
            tokens.extend(_SPLIT_RE.split(str(item or "").replace("\r", "")))
    else:
        tokens = []
    names: list[str] = []
    for token in tokens:
        text = str(token or "").strip().strip("`'\"“”‘’（）()[]【】")
        if not text:
            continue
        name = text if text in CATEGORY_NAMES else ALIASES.get(text)
        if not name:
            # 「听力细节理解」这类带后缀的写法：按最长类目名包含匹配
            for candidate in sorted(CATEGORY_NAMES, key=len, reverse=True):
                if candidate in text:
                    name = candidate
                    break
        if name and name not in names:
            names.append(name)
    if not names:
        return ["其他"], "fallback"
    return names, "model"


def prompt_rules() -> str:
    """出题/批改/工具 schema 共用的格式契约。"""
    names = "、".join(CATEGORY_NAMES)
    return f"""【知识点标注（必须遵守）】
- 每道题固定写成两部分：先以「【第N题】」开头写题干；题干结束后另起一行写「【知识点】A、B」。
- A、B 只能从这 8 个类目里选 1–3 个，必须原样照抄，用「、」分隔：
  {names}。
- 不要用同义词（如「单词」「从句」「连读」），不要写解释，不要重复类目；
  一题同时考多个方面时，选最核心的 1–3 个。
- 批改块里不要重复上一题的【知识点】；下一题的知识点只写在下一题的题块里。

【判分口径（必须遵守）】
- 批改的第一行只能是「【批改】正确」或「【批改】错误」。
- 只要不是完全正确（含部分正确、漏点、表述不完整），一律写「【批改】错误」。
- 先给对错结论，再另起一行讲原因。"""
