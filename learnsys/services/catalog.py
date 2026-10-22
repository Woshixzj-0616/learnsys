"""最小服务目录：把已有服务函数挂到统一 kind 上，只做参数白名单与分派。

业务逻辑仍在 `translate.py` / `analysis.py`；这里不复制一份实现。
"""
from __future__ import annotations

from learnsys.services import analysis, textops, translate


class UnknownService(LookupError):
    """kind 不在目录里。"""


def _translate(payload: dict) -> dict:
    return translate.translate(
        payload["text"], kind=payload.get("kind") or "word",
        context=payload.get("context"))


def _translate_items(payload: dict) -> dict:
    return translate.translate_sentences(
        payload.get("sentences") or [], paper_id=payload.get("paper_id") or "",
        section=payload.get("section") or "", item=payload.get("item") or "")


def _define(payload: dict) -> dict:
    """查词 = 带语境和音标的单词翻译，复用同一份缓存。"""
    return translate.translate(
        payload["text"], kind="word", context=payload.get("context"))


def _cet6_analyze(payload: dict) -> dict:
    return analysis.submit(payload, force=bool(payload.get("force")))


SERVICES: dict[str, dict] = {
    "translate": {
        "description": "单词 / 句子翻译（带缓存）",
        "mode": "sync",
        "params": ["text", "kind", "context"],
        "required": ["text"],
        "handler": _translate,
    },
    "define": {
        "description": "查词：音标 + 释义 + 语境（复用翻译缓存）",
        "mode": "sync",
        "params": ["text", "context"],
        "required": ["text"],
        "handler": _define,
    },
    "explain": {
        "description": "用中文解释一句话或一个概念",
        "mode": "sync",
        "params": ["text", "context"],
        "required": ["text"],
        "handler": lambda payload: textops.complete(
            "explain", payload["text"], payload.get("context") or ""),
    },
    "summarize": {
        "description": "把一段内容压缩成中文要点",
        "mode": "sync",
        "params": ["text", "context"],
        "required": ["text"],
        "handler": lambda payload: textops.complete(
            "summarize", payload["text"], payload.get("context") or ""),
    },
    "translate_items": {
        "description": "一段的逐句翻译（12 句分块 + 缓存）",
        "mode": "sync",
        "params": ["sentences", "paper_id", "section", "item"],
        "required": ["sentences"],
        "handler": _translate_items,
    },
    "cet6_analyze": {
        "description": "六级分析（后台任务，轮询 /api/cet6/analysis/{id}）",
        "mode": "job",
        "params": ["paper_id", "paper", "section", "item", "scope",
                   "sentences", "context", "force"],
        "required": ["sentences"],
        "handler": _cet6_analyze,
    },
}


def describe(kind: str) -> dict:
    """目录里的一项（不含 handler）。"""
    spec = SERVICES.get(kind)
    if spec is None:
        raise UnknownService(kind)
    return {
        "kind": kind,
        "description": spec["description"],
        "mode": spec["mode"],
        "params": list(spec["params"]),
        "required": list(spec["required"]),
    }


def catalog() -> dict:
    return {"items": [describe(kind) for kind in SERVICES]}


def dispatch(kind: str, payload: dict | None) -> tuple[dict, str]:
    """校验并调用；返回 `(结果, mode)`。参数错误抛 ValueError。"""
    spec = SERVICES.get(kind)
    if spec is None:
        raise UnknownService(kind)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("参数必须是对象")
    unknown = sorted(set(payload) - set(spec["params"]))
    if unknown:
        raise ValueError("不支持的参数：" + "、".join(unknown))
    missing = [key for key in spec["required"] if payload.get(key) in (None, "", [])]
    if missing:
        raise ValueError("缺少参数：" + "、".join(missing))
    return spec["handler"](payload), spec["mode"]
