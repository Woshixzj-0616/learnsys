"""结构化上下文快照：界面把「用户此刻在看什么」交给 Agent。

只允许固定九个键，字符串按上限截断，序列化后超过 20KB 直接拒绝。
这样提示词里出现的是一个可控、可审计的对象，而不是前端随手塞的一大坨 JSON。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

MAX_BYTES = 20 * 1024
MAX_SELECTION = 2000
MAX_TITLE = 200
MAX_SURROUNDING = 1000
MAX_RECENT_ACTIONS = 20

_ALLOWED_KEYS = {
    "surface", "object_type", "object_id", "title", "selection",
    "surrounding", "learning_state", "recent_actions", "provenance",
}


def _text(value, cap: int) -> str:
    text = str(value or "")
    return text if len(text) <= cap else text[:cap]


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _short_dict(value: dict, cap: int) -> dict:
    out = {}
    for key, item in (value or {}).items():
        if not isinstance(key, str):
            continue
        if isinstance(item, str):
            out[key] = _text(item, cap)
        elif isinstance(item, (int, float, bool)) or item is None:
            out[key] = item
        elif isinstance(item, (list, tuple)):
            out[key] = [_text(x, cap) for x in list(item)[:20]]
        elif isinstance(item, dict):
            out[key] = {str(k): _text(v, cap) for k, v in item.items()
                        if isinstance(k, str) and isinstance(v, (str, int, float, bool))}
    return out


def _action(value, cap: int = 300):
    if isinstance(value, str):
        return _text(value, cap)
    if isinstance(value, dict):
        return {str(k): _text(v, cap) for k, v in value.items()
                if isinstance(k, str) and isinstance(v, (str, int, float, bool))}
    return None


@dataclass(frozen=True)
class ContextSnapshot:
    surface: str
    object_type: str
    object_id: str
    title: str = ""
    selection: str = ""
    surrounding: dict = field(default_factory=dict)
    learning_state: dict = field(default_factory=dict)
    recent_actions: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "ContextSnapshot":
        """白名单 + 截断；多余键丢掉，超出 20KB 抛 ValueError。"""
        if not isinstance(raw, dict):
            raise ValueError("上下文必须是对象")
        data = {key: raw.get(key) for key in _ALLOWED_KEYS if key in raw}
        raw_actions = data.get("recent_actions")
        if not isinstance(raw_actions, (list, tuple)):
            raw_actions = []
        recent = []
        for item in list(raw_actions)[:MAX_RECENT_ACTIONS]:
            action = _action(item)
            if action is not None:
                recent.append(action)
        snapshot = cls(
            surface=_text(data.get("surface"), 40),
            object_type=_text(data.get("object_type"), 40),
            object_id=_text(data.get("object_id"), 300),
            title=_text(data.get("title"), MAX_TITLE),
            selection=_text(data.get("selection"), MAX_SELECTION),
            surrounding=_short_dict(_dict(data.get("surrounding")), MAX_SURROUNDING),
            learning_state=_short_dict(_dict(data.get("learning_state")), MAX_SURROUNDING),
            recent_actions=recent,
            provenance=_short_dict(_dict(data.get("provenance")), 300),
        )
        if len(snapshot.canonical().encode("utf-8")) > MAX_BYTES:
            raise ValueError("上下文太大")
        return snapshot

    def to_dict(self) -> dict:
        return {
            "surface": self.surface,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "title": self.title,
            "selection": self.selection,
            "surrounding": self.surrounding,
            "learning_state": self.learning_state,
            "recent_actions": self.recent_actions,
            "provenance": self.provenance,
        }

    def canonical(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha1(self.canonical().encode("utf-8")).hexdigest()[:16]

    def render_text(self, max_chars: int = 2000) -> str:
        """给模型看的纯文本；不塞 JSON，省 token 也更好读。"""
        lines: list[str] = []
        head = self.title.strip() or self.object_id.strip() or "当前上下文"
        lines.append(f"【{head}】")
        lines.append(f"对象：{self.object_type or '未知'} {self.object_id}".strip())
        if self.selection.strip():
            lines.append("选中的内容：\n" + self.selection.strip())
        if self.surrounding:
            lines.append("周围内容：")
            for key, value in self.surrounding.items():
                if str(value).strip():
                    lines.append(f"- {key}：{value}")
        if self.learning_state:
            lines.append("学习状态：")
            for key, value in self.learning_state.items():
                if isinstance(value, (list, tuple)):
                    value = "、".join(str(x) for x in value) or "无"
                lines.append(f"- {key}：{value}")
        if self.recent_actions:
            lines.append("最近操作：")
            for item in self.recent_actions[:10]:
                if isinstance(item, dict):
                    item = " · ".join(f"{k}={v}" for k, v in item.items())
                lines.append(f"- {item}")
        provenance = "；".join(f"{k}={v}" for k, v in self.provenance.items())
        lines.append("来源：" + (provenance or self.surface or "未知"))
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[:max_chars] + "…"
