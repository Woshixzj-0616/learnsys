"""Web 工作台 ↔ 原生快捷栏的桥。

后端跑在 Qt 进程里，但 FastAPI 的请求处理线程**不能直接碰 Qt 控件**。
所以这里只存“发信号”的函数：AskApp 注册的是 Qt Signal.emit，
请求线程调用它 → Qt 排队回到主线程执行，安全。
"""
from __future__ import annotations

from typing import Callable

_ACTIONS: dict[str, Callable[[], None]] = {}


def register_ui(**actions: Callable[[], None]) -> None:
    """AskApp 启动时注册：show_bar / pick。"""
    _ACTIONS.clear()
    _ACTIONS.update({name: fn for name, fn in actions.items() if callable(fn)})


def available() -> bool:
    """当前后台是否接在 Qt 主进程上（能调快捷栏）。"""
    return bool(_ACTIONS)


def clear_ui() -> None:
    _ACTIONS.clear()


def call_ui(name: str) -> bool:
    action = _ACTIONS.get(name)
    if action is None:
        return False
    try:
        action()
        return True
    except Exception:
        return False
