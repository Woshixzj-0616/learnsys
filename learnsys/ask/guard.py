"""后台守护：后台掉了自动拉起来。

为什么要有这个：任务栏 / 开始菜单点的是 PWA 网页壳，**浏览器不能启动本地进程**；
后台一旦退出（崩溃、被父进程带走、误关），点开就只剩「后台未连接」。
做法：Windows 计划任务每分钟跑一次 `学习工作台.exe --watchdog`——
① 有「手动退出」标记 → 不动（用户自己关的，别烦他）；
② 8765 / 8766 上有健康后台 → 直接退（绝大多数时候就是这样，开销很小）；
③ 都没有 → 按后台模式拉起来（横栏 + 托盘回来，网页窗口等用户自己开）。

刻意不碰 Qt：计划任务每秒可能跑一次，这里越薄越好。
"""
from __future__ import annotations

import datetime
import json
import pathlib
import subprocess

from learnsys import config

TASK_NAME = "LearnSysGuard"          # 计划任务名用 ASCII，schtasks 对中文名兼容性差
TASK_EVERY_MINUTES = 1
QUIT_MARKER_NAME = "后台已手动退出.json"


def marker_path(data_root: pathlib.Path | str | None = None) -> pathlib.Path:
    return pathlib.Path(data_root or config.DATA_ROOT) / QUIT_MARKER_NAME


def mark_quit(data_root: pathlib.Path | str | None = None) -> None:
    """托盘「退出」时落一个标记 —— 守护看到它就不再拉起。"""
    path = marker_path(data_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"at": datetime.datetime.now().isoformat(timespec="seconds")},
                                   ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def clear_quit(data_root: pathlib.Path | str | None = None) -> None:
    """任何「正常启动」都清掉标记（双击图标 / 开机自启 / 网页点「启动后台」）。"""
    try:
        marker_path(data_root).unlink(missing_ok=True)
    except OSError:
        pass


def quit_requested(data_root: pathlib.Path | str | None = None) -> bool:
    try:
        return marker_path(data_root).exists()
    except OSError:
        return False


def should_start(*, quit_requested: bool, healthy: bool) -> bool:
    """--watchdog 的唯一判断：用户没手动退出、而且确实没有健康后台。"""
    return not quit_requested and not healthy


# ---- 计划任务（schtasks）----

def task_installed() -> bool:
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME],
                                capture_output=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


# schtasks 造出来的任务默认「用电池时不启动」—— 笔记本上等于永远不跑（真踩过）。
# schtasks 没有对应开关，只能用 Task Scheduler 的 PowerShell 接口改。
_ALLOW_ON_BATTERY = (
    "$t = Get-ScheduledTask -TaskName '{name}'; "
    "$t.Settings.DisallowStartIfOnBatteries = $false; "
    "$t.Settings.StopIfGoingOnBatteries = $false; "
    "$t.Settings.StartWhenAvailable = $true; "
    "Set-ScheduledTask -TaskName '{name}' -Settings $t.Settings | Out-Null"
).format(name=TASK_NAME)


def _allow_on_battery() -> bool:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _ALLOW_ON_BATTERY],
            capture_output=True, timeout=30)
        return result.returncode == 0
    except Exception:
        return False


def install_task(command: str) -> tuple[bool, str]:
    """command 是给任务用的完整命令行，例如 `"D:\\...\\学习工作台.exe" --watchdog`。"""
    try:
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", command,
             "/SC", "MINUTE", "/MO", str(TASK_EVERY_MINUTES), "/F"],
            capture_output=True, timeout=20)
    except Exception as exc:
        return False, f"计划任务没装上：{exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or b"").decode("gbk", "replace").strip()
        return False, f"计划任务没装上：{detail or result.returncode}"
    note = "" if _allow_on_battery() else "（电池限制没改掉，笔记本上可能不跑）"
    return True, (f"后台守护已开：每 {TASK_EVERY_MINUTES} 分钟查一次，"
                  f"后台掉线自动拉起。{note}")


def remove_task() -> tuple[bool, str]:
    try:
        result = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                                capture_output=True, timeout=15)
    except Exception as exc:
        return False, f"计划任务没删掉：{exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or b"").decode("gbk", "replace").strip()
        return False, f"计划任务没删掉：{detail or result.returncode}"
    return True, "后台守护已关。"
