# -*- coding: utf-8 -*-
"""部署：停守护/后台 → 备份 → 换入新构建 → 起后台 → 健康检查 → 恢复守护。

默认只做预检（dry-run），不会改任何东西；真正执行必须加 `--yes`。
失败会尽量自动回滚到部署前的目录，并把失败目录保留下来排查。

    .venv\\Scripts\\python.exe tools\\deploy.py                 # 预检
    .venv\\Scripts\\python.exe tools\\deploy.py --yes           # 真正部署
    .venv\\Scripts\\python.exe tools\\deploy.py --rollback      # 预检回滚
    .venv\\Scripts\\python.exe tools\\deploy.py --rollback --yes
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PROD = ROOT / "dist" / "学习工作台"
DEFAULT_BUILD = ROOT / "dist-build" / "学习工作台"
EXE_NAME = "学习工作台.exe"
GUARD_TASK = "LearnSysGuard"
PORTS = (8765, 8766)
DETACHED = 0x00000008
NEW_GROUP = 0x00000200


class DeployError(Exception):
    """部署失败 —— 消息直接给人看。"""


# ---- 小工具 ----

def say(message: str) -> None:
    print(message, flush=True)


def stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def safe_version(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z._-]+", "_", str(text or "").strip())
    return value[:40] or "unknown"


def unique_path(path: pathlib.Path) -> pathlib.Path:
    if not path.exists():
        return path
    for index in range(2, 100):
        candidate = path.with_name(f"{path.name}-{index}")
        if not candidate.exists():
            return candidate
    raise DeployError(f"同名目录太多，没法定新名字：{path}")


def _ps(script: str, timeout: float = 30) -> tuple[int, str, str]:
    """跑一段 PowerShell（-EncodedCommand，中文路径不用拼引号）。"""
    if os.name != "nt":
        return 1, "", "这个脚本只在 Windows 上跑"
    prefix = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    encoded = base64.b64encode(
        (prefix + script).encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, timeout=timeout)
    except Exception as exc:
        return 1, "", str(exc)
    return (result.returncode,
            result.stdout.decode("utf-8", "replace").strip(),
            result.stderr.decode("utf-8", "replace").strip())


# ---- 健康检查 ----

def health(port: int, timeout: float = 0.8) -> dict | None:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{int(port)}/api/health", timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def live_backend(ports=PORTS) -> tuple[int, dict] | None:
    for port in ports:
        data = health(port)
        if data and data.get("ok"):
            return int(port), data
    return None


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
            return True
    except OSError:
        return False


def wait_healthy(*, ports=PORTS, expect_version: str = "", timeout: float = 60,
                 require_quickbar: bool = True) -> tuple[int, dict] | None:
    """等新后台起来；版本对不上、或不是带快捷栏的进程都不算成功。"""
    deadline = time.monotonic() + max(1.0, timeout)
    seen: dict[int, str] = {}
    while time.monotonic() < deadline:
        for port in ports:
            data = health(port)
            if not data or not data.get("ok"):
                continue
            seen[int(port)] = str(data.get("version") or "")
            if expect_version and str(data.get("version") or "") != expect_version:
                continue
            if require_quickbar and not data.get("quickbar"):
                continue
            return int(port), data
        time.sleep(0.5)
    if seen:
        detail = "；".join(f"{port} 上是 {version or '未知版本'}"
                          for port, version in seen.items())
        raise DeployError(f"健康检查超时（{detail}）")
    raise DeployError(f"健康检查超时：{int(timeout)} 秒内 8765 / 8766 都没有后台")


def wait_down(*, ports=PORTS, timeout: float = 20) -> None:
    deadline = time.monotonic() + max(1.0, timeout)
    while time.monotonic() < deadline:
        # 健康接口没了还要确认端口真的释放：换目录前不能有进程占着文件。
        if not live_backend(ports) and not any(port_open(port) for port in ports):
            return
        time.sleep(0.3)
    raise DeployError("旧后台停掉后仍有服务占着 8765 / 8766；先手动处理")


# ---- 守护任务 ----

def guard_state() -> str | None:
    """Ready / Running / Disabled；没有这个任务返回 None。"""
    code, out, _ = _ps(
        "try { (Get-ScheduledTask -TaskName '%s' -ErrorAction Stop).State } "
        "catch { 'MISSING' }" % GUARD_TASK)
    if code != 0 or not out or out == "MISSING":
        return None
    return out.strip()


def set_guard(enabled: bool) -> None:
    action = ("Enable-ScheduledTask" if enabled else "Disable-ScheduledTask")
    code, out, err = _ps(
        f"{action} -TaskName '{GUARD_TASK}' -ErrorAction Stop | Out-Null; "
        f"(Get-ScheduledTask -TaskName '{GUARD_TASK}').State")
    if code != 0:
        raise DeployError(f"守护任务{'启用' if enabled else '禁用'}失败：{err or out}")
    if enabled:
        _ps(f"Start-ScheduledTask -TaskName '{GUARD_TASK}'", timeout=15)


# ---- 进程 ----

def stop_backend(prod: pathlib.Path) -> list[int]:
    """只停生产目录里的那个 exe，不误杀别的副本。"""
    exe = str((prod / EXE_NAME).resolve()).replace("'", "''")
    code, out, err = _ps(
        f"$p='{exe}'; $ids=@(); "
        "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $p } | "
        "ForEach-Object { $ids += $_.ProcessId; "
        "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
        "$ids -join ','")
    if code != 0:
        raise DeployError(f"停后台失败：{err or out}")
    return [int(item) for item in out.split(",") if item.strip().isdigit()]


def start_backend(prod: pathlib.Path):
    exe = (prod / EXE_NAME).resolve()
    if not exe.is_file():
        raise DeployError(f"找不到可执行文件：{exe}")
    flags = DETACHED | NEW_GROUP if os.name == "nt" else 0
    return subprocess.Popen(
        [str(exe), "--background"], cwd=str(prod),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)


# ---- 目录 ----

def backup_dir_for(prod: pathlib.Path, version: str) -> pathlib.Path:
    return unique_path(prod.with_name(f"{prod.name}-{safe_version(version)}-backup"))


def latest_backup(prod: pathlib.Path) -> pathlib.Path | None:
    if not prod.parent.is_dir():
        return None
    candidates = [path for path in prod.parent.glob(f"{prod.name}-*-backup")
                  if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def swap_in(build: pathlib.Path, prod: pathlib.Path, backup: pathlib.Path) -> None:
    """生产目录 → 备份；构建目录 → 生产目录。复制失败就把备份挪回去。"""
    if prod.exists():
        shutil.move(str(prod), str(backup))
    try:
        shutil.copytree(build, prod)
    except Exception:
        if prod.exists():
            shutil.rmtree(prod, ignore_errors=True)
        if backup.exists():
            shutil.move(str(backup), str(prod))
        raise


def rollback_from(prod: pathlib.Path, backup: pathlib.Path,
                  failed_label: str) -> pathlib.Path:
    """把备份换回生产目录；失败目录保留，便于排查。"""
    failed = unique_path(prod.with_name(f"{prod.name}-{failed_label}-{stamp()}"))
    if prod.exists():
        shutil.move(str(prod), str(failed))
    shutil.move(str(backup), str(prod))
    return failed


# ---- 预检 ----

def preflight(build: pathlib.Path, prod: pathlib.Path, *, rollback: bool,
              expect_version: str, timeout: float) -> dict:
    if not (build / EXE_NAME).is_file() and not rollback:
        raise DeployError(f"构建目录里没有 {EXE_NAME}：{build}（先打包）")
    if not prod.is_dir():
        raise DeployError(f"生产目录不存在：{prod}（首次部署请手动）")
    live = live_backend()
    backup = latest_backup(prod) if rollback else None
    if rollback and backup is None:
        raise DeployError(f"没有找到可回滚的备份：{prod.parent}\\{prod.name}-*-backup")
    return {
        "build": build, "prod": prod, "backup": backup, "live": live,
        "guard": guard_state(), "expect_version": expect_version,
        "timeout": timeout,
    }


def print_plan(info: dict, *, rollback: bool) -> None:
    say("=== 部署预检（dry-run：没有改动任何东西）===")
    say(f"构建目录：{info['build']}")
    say(f"生产目录：{info['prod']}")
    if info["live"]:
        port, data = info["live"]
        say(f"当前后台：{port} 端口，版本 {data.get('version') or '未知'}，"
            f"快捷栏 {'有' if data.get('quickbar') else '无'}")
    else:
        say("当前后台：8765 / 8766 都没有响应")
    say(f"守护任务：{info['guard'] or '未安装'}")
    if rollback:
        say(f"回滚备份：{info['backup']}")
        say("流程：停后台 → 当前目录改名留档 → 备份换回 → 起后台 → 健康检查 → 恢复守护")
    else:
        version = (info["live"][1].get("version") if info["live"] else "") or "unknown"
        say(f"计划备份：{backup_dir_for(info['prod'], version)}")
        say("流程：禁用守护 → 停后台 → 备份 → 复制新构建 → --background 启动 → "
            "轮询 /api/health → 恢复守护")
        say("失败时自动回滚，并保留失败目录。")
    if info["expect_version"]:
        say(f"版本要求：{info['expect_version']}")
    say("确认执行请加 --yes。")


# ---- 执行 ----

def _restore_guard(original: str | None) -> None:
    if original is None or original == "Disabled":
        return
    try:
        set_guard(True)
        say("守护任务已恢复。")
    except DeployError as exc:
        say(f"注意：{exc}（请手动检查计划任务 {GUARD_TASK}）")


def run_deploy(info: dict, *, rollback: bool) -> int:
    prod = info["prod"]
    original_guard = info["guard"]
    swapped_backup: pathlib.Path | None = None
    standby: pathlib.Path | None = None
    try:
        if original_guard is not None and original_guard != "Disabled":
            set_guard(False)
            say("守护任务已临时禁用。")
        pids = stop_backend(prod)
        say(f"已停后台进程：{pids or '（本来没在跑）'}")
        wait_down(timeout=20)
        if rollback:
            standby = rollback_from(prod, info["backup"], "回滚前")
            say(f"备份已换回；回滚前目录：{standby}")
        else:
            live = info["live"]
            version = (live[1].get("version") if live else "") or stamp()
            backup = backup_dir_for(prod, version)
            swap_in(info["build"], prod, backup)
            swapped_backup = backup
            say(f"旧版已备份到：{backup}")
            say(f"新构建已换入：{prod}")
        start_backend(prod)
        say("新后台已启动，等健康检查…")
        port, data = wait_healthy(
            expect_version=info["expect_version"], timeout=info["timeout"])
        say(f"部署成功：{port} 端口，版本 {data.get('version') or '未知'}，"
            f"快捷栏 {'有' if data.get('quickbar') else '无'}")
        return 0
    except Exception as exc:
        say(f"部署失败：{exc}")
        if rollback:
            where = f"；前一个版本保留在：{standby}" if standby else ""
            say(f"回滚版本没通过健康检查，目录保持为回滚版本{where}")
        elif swapped_backup is not None and swapped_backup.exists():
            try:
                stop_backend(prod)
                wait_down(timeout=10)
                failed = rollback_from(prod, swapped_backup, "失败")
                say(f"已回滚；失败目录保留在：{failed}")
                start_backend(prod)
                port, data = wait_healthy(timeout=min(info["timeout"], 60))
                say(f"回滚后后台恢复：{port} 端口，版本 {data.get('version') or '未知'}")
            except Exception as rollback_exc:
                say(f"注意：自动回滚也失败：{rollback_exc}（备份目录没有删，先别重启机器）")
        else:
            say("失败发生在换入之前，生产目录没有改动。")
            try:
                if (prod / EXE_NAME).is_file():
                    start_backend(prod)
                    port, data = wait_healthy(timeout=min(info["timeout"], 60))
                    say(f"旧后台已重新拉起：{port} 端口，版本 {data.get('version') or '未知'}")
            except Exception as restart_exc:
                say(f"注意：旧后台没拉起来：{restart_exc}")
        return 1
    finally:
        _restore_guard(original_guard)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学习工作台部署 / 回滚")
    parser.add_argument("--build", default=str(DEFAULT_BUILD), help="新构建目录")
    parser.add_argument("--prod", default=str(DEFAULT_PROD), help="生产目录")
    parser.add_argument("--rollback", action="store_true", help="回滚到最近一次备份")
    parser.add_argument("--expect-version", default="", help="健康检查要求的版本号")
    parser.add_argument("--timeout", type=float, default=60, help="健康检查超时（秒）")
    parser.add_argument("--yes", action="store_true", help="真正执行；不加只预检")
    args = parser.parse_args(argv)

    if os.name != "nt":
        say("这个脚本只在 Windows 上跑。")
        return 1
    build = pathlib.Path(args.build)
    prod = pathlib.Path(args.prod)
    try:
        info = preflight(build, prod, rollback=args.rollback,
                         expect_version=args.expect_version, timeout=args.timeout)
    except DeployError as exc:
        say(f"预检失败：{exc}")
        return 1
    print_plan(info, rollback=args.rollback)
    if not args.yes:
        return 0
    return run_deploy(info, rollback=args.rollback)


if __name__ == "__main__":
    raise SystemExit(main())
