"""本机浏览器定位：环境变量优先，其次 Edge，再 Chrome。

放在核心层：`browser.manager`（独立 profile / CDP）和 `ask.workbench`
（`--app=` 窗口外壳）都要用，但两者都不该反过来依赖界面层。
"""
from __future__ import annotations

import os
import pathlib
import shutil


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
