"""P26.2 写操作审批：钩子脚本、令牌、提议摘要与 diff。

外部 agent 真正执行写操作时，Claude Code 在 PreToolUse 钩子里把工具名和参数
交给本模块；这里只负责「说清楚要做什么」，等人在网页上点允许/拒绝。
Codex 走沙箱整任务授权，不经过这里。
"""
from __future__ import annotations

import difflib
import json
import pathlib
import secrets
import threading

GATED_TOOLS = (
    "Write", "Edit", "MultiEdit", "NotebookEdit",
    "Bash", "BashOutput", "KillShell",
)
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
COMMAND_TOOLS = {"Bash", "BashOutput", "KillShell"}

READ_LIMIT = 200_000
PREVIEW_LIMIT = 6000
PAYLOAD_LIMIT = 20_000

# 钩子命令只依赖 curl.exe（Win10 1803+ 自带）。工作台进程把 URL / 令牌 / 任务号
# 放进子进程环境变量，脚本本身不含任何密钥。
HOOK_CMD = """@echo off
curl.exe -s --max-time 650 -X POST -H "Content-Type: application/json" -H "X-Learnsys-Hook: %LEARNSYS_HOOK_TOKEN%" -H "X-Learnsys-Task: %LEARNSYS_TASK_ID%" --data-binary @- "%LEARNSYS_HOOK_URL%"
if errorlevel 1 echo {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"approval service unavailable"}}
"""

_BROKER: dict[str, int] = {}
_BROKER_LOCK = threading.Lock()


def register(task_id: int) -> str:
    """给一次可写任务发一枚一次性令牌；钩子端只能提交，不能替用户点允许。"""
    token = secrets.token_urlsafe(24)
    with _BROKER_LOCK:
        _BROKER[token] = int(task_id)
    return token


def unregister(token: str) -> None:
    if not token:
        return
    with _BROKER_LOCK:
        _BROKER.pop(token, None)


def task_for(token: str) -> int | None:
    with _BROKER_LOCK:
        return _BROKER.get(str(token or ""))


def ensure_hook_cmd(data_root: pathlib.Path) -> pathlib.Path:
    """把钩子脚本落到数据目录；内容固定，重复调用不会重复写。"""
    folder = pathlib.Path(data_root) / "agent_hooks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "approve.cmd"
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if current != HOOK_CMD:
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(HOOK_CMD, encoding="utf-8", newline="\r\n")
        temp.replace(path)
    return path


def hook_settings(cmd_path: pathlib.Path, timeout_s: int = 115) -> str:
    """Claude `--settings` 里只放这一条 PreToolUse 钩子。"""
    command = f'cmd /c "{pathlib.Path(cmd_path).as_posix()}"'
    matcher = "|".join(GATED_TOOLS)
    settings = {"hooks": {"PreToolUse": [{
        "matcher": matcher,
        "hooks": [{"type": "command", "command": command,
                   "timeout": max(10, int(timeout_s))}],
    }]}}
    return json.dumps(settings, ensure_ascii=False)


def hook_response(decision: str, reason: str = "") -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": str(reason or "")[:500],
    }}


def allow(reason: str = "用户已允许") -> dict:
    return hook_response("allow", reason)


def deny(reason: str = "用户拒绝了这次操作") -> dict:
    return hook_response("deny", reason)


def _clip(text: str, limit: int = PREVIEW_LIMIT) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit] + "\n…（预览已截断）"


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(READ_LIMIT)
    except (OSError, ValueError):
        return None


def _diff(old: str, new: str, name: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"当前 {name}", tofile=f"修改后 {name}", lineterm="", n=3)
    return _clip("\n".join(lines))


def _numbered(text: str) -> str:
    lines = str(text or "").splitlines()
    return "\n".join(f"{index + 1:>4} | {line}"
                     for index, line in enumerate(lines[:200]))


def _target_name(path: str) -> str:
    return pathlib.Path(path).name if path else "（未写路径）"


def describe(tool: str, payload: dict | None) -> dict:
    """把一次工具调用翻成界面能直接显示的中文摘要 + 预览。"""
    data = payload if isinstance(payload, dict) else {}
    tool = str(tool or "")
    kind = "other"
    target = ""
    summary = tool or "未知操作"
    preview = ""

    if tool == "Bash":
        kind = "command"
        command = str(data.get("command") or "").strip()
        target = command.splitlines()[0][:200] if command else ""
        summary = f"运行命令：{target or '（空命令）'}"
        note = str(data.get("description") or "").strip()
        preview = (f"# {note}\n{command}" if note else command) or "（空命令）"

    elif tool in ("BashOutput", "KillShell"):
        kind = "command"
        shell_id = str(data.get("shell_id") or data.get("id") or "")
        target = shell_id
        summary = ("读取后台命令输出" if tool == "BashOutput"
                   else "停止后台命令") + (f"（{shell_id}）" if shell_id else "")
        preview = json.dumps(data, ensure_ascii=False, indent=2)

    elif tool == "Write":
        kind = "write"
        path = str(data.get("file_path") or "")
        content = str(data.get("content") or "")
        target = path
        existing = _read_text(path) if path else None
        if existing is None:
            summary = f"新建文件 {_target_name(path)}（{len(content)} 字）"
            preview = "（新文件）\n" + _numbered(content)
        else:
            summary = f"覆盖写入 {_target_name(path)}（{len(content)} 字）"
            preview = _diff(existing, content, path)

    elif tool == "Edit":
        kind = "edit"
        path = str(data.get("file_path") or "")
        old = str(data.get("old_string") or "")
        new = str(data.get("new_string") or "")
        replace_all = bool(data.get("replace_all"))
        target = path
        base = _read_text(path) if path else None
        count = (base.count(old) if base is not None and old else 0)
        summary = f"修改 {_target_name(path)}（替换 {count or '?'} 处"
        summary += "，全部替换）" if replace_all else "）"
        if base is not None and old and old in base:
            updated = base.replace(old, new, -1 if replace_all else 1)
            preview = _diff(base, updated, path)
        else:
            preview = (f"原文没有在文件里找到（可能已被改动）。\n\n"
                       f"--- 要替换的片段 ---\n{old}\n\n"
                       f"--- 替换为 ---\n{new}")

    elif tool == "MultiEdit":
        kind = "edit"
        path = str(data.get("file_path") or "")
        edits = data.get("edits") if isinstance(data.get("edits"), list) else []
        target = path
        summary = f"修改 {_target_name(path)}（{len(edits)} 处编辑）"
        base = _read_text(path) if path else None
        if base is not None:
            updated = base
            for edit in edits:
                if not isinstance(edit, dict):
                    continue
                old = str(edit.get("old_string") or "")
                new = str(edit.get("new_string") or "")
                if old:
                    updated = updated.replace(
                        old, new, -1 if edit.get("replace_all") else 1)
            preview = _diff(base, updated, path)
        else:
            preview = json.dumps(edits, ensure_ascii=False, indent=2)

    elif tool == "NotebookEdit":
        kind = "edit"
        path = str(data.get("notebook_path") or "")
        target = path
        mode = str(data.get("edit_mode") or "replace")
        cell = str(data.get("cell_id") or data.get("cell_number") or "")
        summary = f"编辑 Notebook {_target_name(path)}（{mode} 单元格 {cell or '—'}）"
        preview = str(data.get("new_source") or "")

    else:
        preview = json.dumps(data, ensure_ascii=False, indent=2)

    return {
        "kind": kind,
        "target": str(target)[:1000],
        "summary": str(summary)[:2000],
        "preview": _clip(preview),
        "payload_json": json.dumps(data, ensure_ascii=False)[:PAYLOAD_LIMIT],
    }
