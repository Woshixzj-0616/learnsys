"""全局快捷键：ctypes 调 RegisterHotKey，零第三方依赖。

注册在 Qt 主线程上 —— Windows 把 WM_HOTKEY 投到该线程的消息队列，Qt 事件循环取到时
经 nativeEventFilter 转成 Qt 信号。别的程序占着前台也照样能唤起。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from PySide6 import QtCore

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_MODS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND),
        ("message", wt.UINT),
        ("wParam", wt.WPARAM),
        ("lParam", wt.LPARAM),
        ("time", wt.DWORD),
        ("pt_x", wt.LONG),
        ("pt_y", wt.LONG),
    ]


def parse(spec: str) -> tuple[int, int, str]:
    """'alt+q' → (修饰键掩码, 虚拟键码, 给人看的名字)。解析不了抛 ValueError。"""
    parts = [p for p in spec.replace(" ", "").split("+") if p]
    if not parts:
        raise ValueError("快捷键是空的")
    *mods, key = [p.lower() for p in parts]
    flags = 0
    for m in mods:
        if m not in _MODS:
            raise ValueError(f"不认识的修饰键：{m}")
        flags |= _MODS[m]
    if len(key) == 1 and key.isalpha():
        vk = ord(key.upper())
    elif len(key) == 1 and key.isdigit():
        vk = ord(key)
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    else:
        raise ValueError(f"不认识的主键：{key}")
    pretty = "+".join([m.capitalize() for m in mods] + [key.upper()])
    return flags | MOD_NOREPEAT, vk, pretty


class _HotkeyFilter(QtCore.QAbstractNativeEventFilter):
    def __init__(self, hotkey_id: int, on_hit):
        super().__init__()
        self._id = hotkey_id
        self._on_hit = on_hit

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
            if msg.message == WM_HOTKEY and int(msg.wParam) == self._id:
                self._on_hit()
        return False, 0


class GlobalHotkey(QtCore.QObject):
    """注册一个全局快捷键，按下时发 triggered 信号。"""

    triggered = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, spec: str, parent=None):
        super().__init__(parent)
        self._id = 0xB001
        self._filter = None
        self._ok = False
        self._error = ""
        self.pretty = spec
        try:
            self._mods, self._vk, self.pretty = parse(spec)
        except ValueError as exc:
            self._error = str(exc)
            self._mods = self._vk = 0

    def register(self) -> bool:
        if self._error:
            self.failed.emit(f"快捷键「{self.pretty}」解析不了：{self._error}")
            return False
        ctypes.set_last_error(0)
        if not user32.RegisterHotKey(None, self._id, self._mods, self._vk):
            code = kernel32.GetLastError()
            if code == ERROR_HOTKEY_ALREADY_REGISTERED:
                reason = "这个组合被别的程序占了 —— 去 D:/学习系统/设置.json 里的 hotkey 换一个"
            else:
                reason = f"系统错误码 {code}"
            self.failed.emit(f"注册快捷键 {self.pretty} 失败：{reason}")
            return False
        self._ok = True
        self._filter = _HotkeyFilter(self._id, self.triggered.emit)
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._filter)
        return True

    def unregister(self) -> None:
        if self._ok:
            user32.UnregisterHotKey(None, self._id)
            self._ok = False
        if self._filter is not None:
            app = QtCore.QCoreApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._filter)
            self._filter = None
