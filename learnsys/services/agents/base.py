"""P26.1 Agent 中枢的公共形状：agent 规格、任务事件、argv 与解析分发。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentSpec:
    id: str
    name: str
    kind: str                 # claude / codex / fake
    command: str
    args: list[str] = field(default_factory=list)
    available: bool = True
    note: str = ""
    version: str = ""


@dataclass
class TaskEvent:
    kind: str                 # status / text / tool / error / result
    text: str = ""
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0


def build_argv(spec: AgentSpec, prompt: str, workspace: str) -> list[str]:
    """构造只读参数。任何写/绕过沙箱的开关都不在这里出现。"""
    if spec.kind == "claude":
        return [
            spec.command, "-p", prompt,
            "--output-format", "stream-json", "--verbose",
            "--restricted", "--permission-mode", "plan",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--add-dir", str(workspace),
            *spec.args,
        ]
    if spec.kind == "codex":
        return [
            spec.command, "exec", "--json",
            "--sandbox", "read-only", "--skip-git-repo-check",
            "--ephemeral", "-C", str(workspace),
            *spec.args, prompt,
        ]
    return [spec.command, *spec.args, prompt]


def parse_line(kind: str, line: str) -> list[TaskEvent]:
    """把 CLI 的一行输出翻成界面能显示的事件；解析不了就当普通文本。"""
    text = str(line or "").rstrip("\r\n")
    if not text.strip():
        return []
    if kind == "claude":
        return _parse_claude(text)
    if kind == "codex":
        return _parse_codex(text)
    if kind == "fake":
        return _parse_fake(text)
    return [TaskEvent("text", text)]


def _parse_claude(text: str) -> list[TaskEvent]:
    try:
        event = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [TaskEvent("text", text)]
    if not isinstance(event, dict):
        return [TaskEvent("text", text)]
    kind = event.get("type")
    if kind == "system":
        if event.get("subtype") == "init":
            return [TaskEvent("status", "已启动 Claude Code（只读）")]
        return []
    if kind == "assistant":
        message = event.get("message") or {}
        out: list[TaskEvent] = []
        for item in message.get("content") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                out.append(TaskEvent("text", str(item["text"])))
            elif item.get("type") == "tool_use":
                name = str(item.get("name") or "工具")
                payload = item.get("input") if isinstance(item.get("input"), dict) else {}
                target = (payload.get("file_path") or payload.get("path")
                          or payload.get("pattern") or payload.get("command") or "")
                out.append(TaskEvent("tool", f"{name} {str(target)[:200]}".strip()))
        return out
    if kind == "result":
        return [TaskEvent(
            "result", str(event.get("result") or ""),
            usage=event.get("usage") if isinstance(event.get("usage"), dict) else {},
            cost_usd=float(event.get("total_cost_usd") or 0))]
    if kind == "error":
        return [TaskEvent("error", str(event.get("message") or event))]
    # 观察到的收尾行没有 type，只带 cost/usage
    if "total_cost_usd" in event:
        return [TaskEvent(
            "result", "", usage=event.get("usage") if isinstance(event.get("usage"), dict) else {},
            cost_usd=float(event.get("total_cost_usd") or 0))]
    return []


def _parse_codex(text: str) -> list[TaskEvent]:
    try:
        event = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [TaskEvent("text", text)]
    if not isinstance(event, dict):
        return [TaskEvent("text", text)]
    kind = event.get("type")
    if kind == "thread.started":
        return [TaskEvent("status", "已启动 Codex（只读）")]
    if kind == "turn.started":
        return [TaskEvent("status", "开始执行")]
    if kind == "item.completed":
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        item_kind = item.get("type")
        if item_kind in ("agent_message", "assistant_message"):
            return [TaskEvent("text", str(item.get("text") or ""))]
        if item_kind in ("command_execution", "tool_call"):
            command = item.get("command") or item.get("name") or ""
            return [TaskEvent("tool", str(command)[:300])]
        if item_kind == "error":
            return [TaskEvent("error", str(item.get("message") or item))]
        return []
    if kind == "turn.completed":
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        return [TaskEvent("result", "", usage=usage)]
    if kind == "error":
        return [TaskEvent("error", str(event.get("message") or "Codex 出错"))]
    return []


def _parse_fake(text: str) -> list[TaskEvent]:
    try:
        event = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [TaskEvent("text", text)]
    if not isinstance(event, dict):
        return [TaskEvent("text", text)]
    kind = str(event.get("kind") or "text")
    if kind == "result":
        return [TaskEvent("result", str(event.get("text") or ""),
                          usage=event.get("usage") or {},
                          cost_usd=float(event.get("cost_usd") or 0))]
    return [TaskEvent(kind, str(event.get("text") or ""))]


def workspace_arg(workspace: str | Path) -> str:
    return str(Path(workspace).resolve())
