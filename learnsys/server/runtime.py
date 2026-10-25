"""Web 工作台 ↔ 原生快捷栏的桥。

后端跑在 Qt 进程里，但 FastAPI 的请求处理线程**不能直接碰 Qt 控件**。
所以这里只存“发信号”的函数：AskApp 注册的是 Qt Signal.emit，
请求线程调用它 → Qt 排队回到主线程执行，安全。
"""
from __future__ import annotations

from typing import Callable

_ACTIONS: dict[str, Callable[[], None]] = {}
_STATE: dict[str, Callable[[], dict]] = {}


def register_ui(**actions: Callable[[], None]) -> None:
    """AskApp 启动时注册：show_bar / pick。"""
    _ACTIONS.clear()
    _ACTIONS.update({name: fn for name, fn in actions.items() if callable(fn)})


def register_state(**states: Callable[[], dict]) -> None:
    """AskApp 启动时注册只读状态（录像进度等）。"""
    _STATE.clear()
    _STATE.update({name: fn for name, fn in states.items() if callable(fn)})


def call_state(name: str) -> dict | None:
    """取一份只读状态；没接上/出错返回 None，不把异常抛给 HTTP 层。"""
    fn = _STATE.get(name)
    if fn is None:
        return None
    try:
        value = fn()
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def available() -> bool:
    """当前后台是否接在 Qt 主进程上（能调快捷栏）。"""
    return bool(_ACTIONS)


def clear_ui() -> None:
    _ACTIONS.clear()
    _STATE.clear()


def call_ui(name: str) -> bool:
    action = _ACTIONS.get(name)
    if action is None:
        return False
    try:
        action()
        return True
    except Exception:
        return False
