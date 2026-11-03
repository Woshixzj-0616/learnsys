"""取证门控：排错题需要外部事实、本轮又零证据时，强制先调只读工具取证。

**唯一判据**：`loop.py` 的前置提示/补轮、`turn` 的工具裁剪都从这里取，别各写一份。

口径：
- 用户已经贴了配置原文 / 报错输出 → 不强制联网（`user_text`）；
- 本轮已经有 `web_search` / `fetch_url` / `run_code` 结果 → 不再补轮（`already_evidenced`）；
- 其余需要外部事实的 ops 轮 → `tools_missing`，最多补一轮；
- `ops_gate=off` 完全不干预；`shadow` 只记录，不改变回答。

只做规则判断与提示词拼装，不调模型、不读库。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from learnsys.agent import tools

EVIDENCE_TOOLS = ("web_search", "fetch_url", "run_code")
# 只有「版本 / 默认行为」这类问题才值得强制联网；端口排查、读代码靠本地规则即可。
FACT_HINTS = ("版本", "最新", "默认", "弃用", "兼容")

# 「用户已经给了原文」的保守判据：宁可少判，别把普通提问当成已取证。
_CONFIG_EVIDENCE_RE = re.compile(
    r"server\s*\{|listen\s+\d+|server_name|include\s+/etc/|Traceback \(most recent",
    re.I)
_OUTPUT_EVIDENCE_RE = re.compile(
    r"(?:输出|报错|exit code|退出码)\s*[:：=]\s*\S", re.I)

NUDGE_TEXT = """【本轮系统要求：先取证】
你需要外部事实才能下结论。回答前必须至少调用一次 `web_search` 或 `fetch_url` 查证；
最多 2 次工具调用（一次搜索，必要时再打开一个官方页面），已经拿到官方原文就停止，
不要反复搜索同一问题。查不到就写「没查到，以下为候选原因」。
取证轮不要调用写操作工具（save_* / add_* / rate_* / run_code / open_*），先把证据拿到。"""

UNVERIFIED_NOTE = ("\n\n> **未查证**：本轮没有取得外部证据，以上为候选原因，"
                   "请按验证方法在机器上确认。")


@dataclass(frozen=True)
class GateDecision:
    needed: bool
    kind: str      # none / user_text / already_evidenced / tools_missing
    reason: str


def _user_provided(text: str) -> bool:
    value = str(text or "")
    if not value.strip():
        return False
    if "Traceback (most recent call last)" in value:
        return True
    if _CONFIG_EVIDENCE_RE.search(value) and ("{" in value or len(value) >= 120):
        return True
    return bool(_OUTPUT_EVIDENCE_RE.search(value))


def _has_evidence(evidence) -> bool:
    checker = getattr(evidence, "has_tool", None)
    if not callable(checker):
        return False
    return any(checker(name) for name in EVIDENCE_TOOLS)


def decide(message: str, attachment_text: str, evidence, *,
           ops: bool, ops_gate: str) -> GateDecision:
    """返回这一轮要不要强制取证。`shadow` 也返回真实判断，由调用方决定是否应用。"""
    if not ops or str(ops_gate or "shadow").strip().lower() == "off":
        return GateDecision(False, "none", "未启用取证门控")
    if _user_provided(f"{message or ''}\n{attachment_text or ''}"):
        return GateDecision(False, "user_text", "用户已提供配置/输出原文")
    if not any(word in str(message or "") for word in FACT_HINTS):
        return GateDecision(False, "none", "不需要外部事实")
    if _has_evidence(evidence):
        return GateDecision(False, "already_evidenced", "本轮已有取证工具结果")
    return GateDecision(True, "tools_missing", "需要外部事实但本轮零证据")


def nudge_text() -> str:
    return NUDGE_TEXT


def note_text() -> str:
    return UNVERIFIED_NOTE


def filter_schemas(schemas, keep: tuple[str, ...] = ()):
    """取证轮只留只读工具；`keep` 用于代码调试保留 run_code。"""
    if not schemas:
        return schemas
    confirm = set(tools.CONFIRM_TOOLS)
    return [item for item in schemas
            if str(item.get("name") or "") not in confirm
            or str(item.get("name") or "") in keep]
