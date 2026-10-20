"""把学习台开成一个“应用窗口”，而不是浏览器标签页。

做法：用本机已装的 Edge / Chrome 的 `--app=` 模式打开本地地址 ——
没有地址栏、没有标签页，任务栏上是一个独立窗口；页面的 favicon 和标题照用。

不重写页面：后端一份、HTML 一份，这里只负责“窗口外壳”。
以后想换 WebView2，只改这个文件，页面和接口不用动。
"""
from __future__ import annotations

import ctypes
import os
import pathlib
import shutil
import subprocess
import sys
import time
import webbrowser
from ctypes import wintypes

WINDOW_MARK = "· 学习系统"          # 页面 <title> 统一是「今日 · 学习系统」这种形状
DEFAULT_SIZE = (1440, 900)


def _candidate_browsers():
    env = str(os.environ.get("LEARNSYS_BROWSER") or "").strip()
    if env:
        yield pathlib.Path(env)
    program_files = pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = pathlib.Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    local = os.environ.get("LOCALAPPDATA")
    yield program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    yield program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    yield program_files / "Google" / "Chrome" / "Application" / "chrome.exe"
    yield program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe"
    if local:
        yield pathlib.Path(local) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        yield pathlib.Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"


def find_browser() -> str | None:
    """优先用环境变量指定的浏览器，其次 Edge，再 Chrome；都找不到返回 None。"""
    for path in _candidate_browsers():
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _user32():
    """统一声明 HWND 参数类型 —— 不声明的话 64 位下句柄会被截成 32 位。"""
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                             ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
    return user32


def _work_area() -> tuple[int, int, int, int]:
    """任务栏以外的可用区域（物理像素）。拿不到就退回整个屏幕。"""
    user32 = _user32()
    rect = wintypes.RECT()
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):   # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def fit_window(mark: str = WINDOW_MARK, preferred: tuple[int, int] = DEFAULT_SIZE) -> bool:
    """窗口比屏幕还大 / 跑到屏幕外时，拉回可见区域并居中。

    只在“确实放不下”时动手 —— 用户自己调好的大小和位置要尊重。
    返回 True = 动过窗口。
    """
    if sys.platform != "win32":
        return False
    user32 = _user32()
    left, top, avail_w, avail_h = _work_area()
    for hwnd, _title in _windows_matching(mark):
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            continue
        width, height = rect.right - rect.left, rect.bottom - rect.top
        too_big = width > avail_w - 20 or height > avail_h - 20
        off_screen = (rect.left < left - 40 or rect.top < top - 40
                      or rect.right > left + avail_w + 40
                      or rect.bottom > top + avail_h + 40)
        if not (too_big or off_screen):
            continue
        dpi = user32.GetDpiForWindow(hwnd) or 96
        scale = dpi / 96.0
        want_w = min(int(preferred[0] * scale), avail_w - 40)
        want_h = min(int(preferred[1] * scale), avail_h - 40)
        x = left + (avail_w - want_w) // 2
        y = top + (avail_h - want_h) // 2
        user32.SetWindowPos(hwnd, 0, x, y, want_w, want_h, 0x0004)   # SWP_NOZORDER
        return True
    return False


def _windows_matching(mark: str = WINDOW_MARK) -> list[tuple[int, str]]:
    """枚举可见顶层窗口，找出标题以「· 学习系统」结尾的。"""
    if sys.platform != "win32":
        return []
    user32 = _user32()
    found: list[tuple[int, str]] = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if title.endswith(mark):
            found.append((int(hwnd), title))
        return True

    user32.EnumWindows.argtypes = [proc_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows(proc_type(callback), 0)
    return found


def focus_window(mark: str = WINDOW_MARK) -> bool:
    """已有学习台窗口就把它提到前台；没有返回 False。"""
    if sys.platform != "win32":
        return False
    user32 = _user32()
    for hwnd, _title in _windows_matching(mark):
        user32.ShowWindow(hwnd, 9)                  # SW_RESTORE
        foreground = user32.GetForegroundWindow()
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        foreground_tid = user32.GetWindowThreadProcessId(foreground, None)
        attached = False
        if target_tid and foreground_tid and target_tid != foreground_tid:
            attached = bool(user32.AttachThreadInput(foreground_tid, target_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(foreground_tid, target_tid, False)
        return True
    return False


def _wait_for_window(mark: str = WINDOW_MARK, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _windows_matching(mark):
            return True
        time.sleep(0.12)
    return False


def open_app_window(url: str, size: tuple[int, int] = DEFAULT_SIZE) -> str:
    """用 Edge/Chrome 的应用模式打开；找不到浏览器就退回默认浏览器。

    返回一句人能看懂的“用哪种窗口打开的”，启动提示会用它。
    """
    browser = find_browser()
    if not browser:
        webbrowser.open(url)
        return "默认浏览器"
    width, height = size
    args = [
        browser,
        f"--app={url}",
        f"--window-size={width},{height}",
        "--no-default-browser-check",
    ]
    try:
        subprocess.Popen(args, close_fds=True)
    except OSError:
        webbrowser.open(url)
        return "默认浏览器"
    # Chromium 有“记住上次窗口大小”的行为，--window-size 不一定生效；
    # 等窗口出来后只修“比屏幕大 / 跑到屏外”的情况，正常大小不动。
    if _wait_for_window():
        fit_window(preferred=size)
    return pathlib.Path(browser).name


def open_or_focus(url: str, size: tuple[int, int] = DEFAULT_SIZE) -> str:
    """已经开着就聚焦，没开才新开一个应用窗口。"""
    if focus_window():
        fit_window(preferred=size)
        return "已聚焦现有学习台"
    return open_app_window(url, size)
