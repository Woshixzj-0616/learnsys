"""系统副作用工具：打开本机文件 / 启动程序。

网页 Agent 只能碰资料库和轻量工具；这两个工具补上「真的在电脑上做一件事」，
但全部走人工确认（`schemas.CONFIRM_TOOLS`），并且校验规则只在 `services/ops.py` 里写一次。
"""
from __future__ import annotations

from learnsys.services import ops
from learnsys.browser.manager import get_manager


def open_file(path: str) -> str:
    """用默认程序打开文件或文件夹；失败返回中文原因，不抛给模型。"""
    try:
        return ops.open_path(str(path or ""))
    except ValueError as exc:
        return f"没有打开：{exc}"
    except OSError as exc:
        return f"没有打开：系统拒绝了这个操作（{exc}）"


def launch_app(name: str) -> str:
    """按开始菜单名字启动程序；找不到时返回候选，不猜、不执行。"""
    try:
        return ops.launch_by_name(str(name or ""))
    except ValueError as exc:
        return f"没有启动：{exc}"
    except OSError as exc:
        return f"没有启动：系统拒绝了这个操作（{exc}）"


def open_url(url: str) -> str:
    """在工作台管理的独立浏览器里打开网址；拒绝时返回「没有打开」+ 原因。"""
    try:
        result = get_manager().open_url(str(url or ""))
    except ValueError as exc:
        return f"没有打开：{exc}"
    except Exception as exc:
        return f"没有打开：{exc}"
    return str(result.get("message") or "没有打开：浏览器没有响应。")


def browser_status() -> str:
    """工作台浏览器的运行状态；记录暂停时不暴露当前页。"""
    try:
        status = get_manager().status()
    except Exception as exc:
        return f"读浏览器状态失败：{exc}"
    if not status.get("running"):
        return f"工作台浏览器没有运行（{status.get('message') or '未启动'}）。"
    if status.get("paused"):
        return "工作台浏览器正在运行，但记录已暂停 —— 不提供当前页面信息。"
    current = status.get("current") or {}
    title = str(current.get("title") or "（无标题）")
    url = str(current.get("url") or "")
    return f"工作台浏览器运行中。当前标签：{title} — {url}"


def browser_history(limit: int = 20, days: int = 7) -> str:
    """最近的浏览记录（时间 / 标题 / 域名 / URL），最多 50 条。"""
    limit = max(1, min(50, int(limit or 20)))
    days = max(0, int(days or 0))
    try:
        items = get_manager().history(limit=limit, days=days)
    except Exception as exc:
        return f"读浏览记录失败：{exc}"
    if not items:
        return "最近没有浏览记录。"
    lines = ["最近的浏览记录（新 → 旧）："]
    for item in items:
        title = " ".join(str(item.get("title") or "").split())[:80] or "（无标题）"
        url = str(item.get("url") or "")[:300]
        lines.append(f"- {item.get('ts')} · {title} · {item.get('domain')} · {url}")
    return "\n".join(lines)
