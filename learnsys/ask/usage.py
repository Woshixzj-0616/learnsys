"""算这个程序在硬盘上占了多少（给横栏显示用）。

三块：模型 / 数据（D 盘专用文件夹，按天分）/ 代码；跳过 .git、__pycache__、.venv 之类。
"""
from __future__ import annotations

import os
import pathlib
import shutil
from dataclasses import dataclass

from learnsys import config

SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules", ".idea",
        "dist", "build"}          # 打包产物不算「代码占的盘」，否则打完包数字凭空涨 50MB


@dataclass
class Usage:
    short: str     # 收起成小条时显示的那一小段
    line: str      # 展开时底部那一行
    detail: str    # 鼠标悬停看的明细


def _dir_size(path: pathlib.Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def report() -> dict:
    """模型 / 数据 / 代码三块 + 今天那个文件夹。"""
    model = _dir_size(config.ROOT / "models")
    code = 0
    for root, dirs, files in os.walk(config.ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP]
        parts = pathlib.Path(root).relative_to(config.ROOT).parts
        if parts and parts[0] == "models":
            continue
        for name in files:
            try:
                code += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    data = _dir_size(config.DATA_ROOT)
    return {"模型": model, "数据": data, "代码": code,
            "今天": _dir_size(config.day_dir()), "合计": model + data + code}


def summary() -> Usage:
    """给横栏用的三份文案（小条 / 一行 / 明细）。"""
    info = report()
    drive = (config.DATA_ROOT.drive or "D:").rstrip("\\")
    line = f"本程序在 {drive} 盘占 {human(info['合计'])}（数据 {human(info['数据'])}）"
    try:
        line += f" ｜ {drive} 盘还剩 {human(shutil.disk_usage(drive + chr(92)).free)}"
    except OSError:
        pass
    detail = (f"模型 {human(info['模型'])} ｜ 数据 {human(info['数据'])}"
              f" ｜ 代码 {human(info['代码'])}\n"
              f"今天（{config.day_dir().name}）{human(info['今天'])}\n"
              f"数据：{config.DATA_ROOT}\n代码：{config.ROOT}")
    return Usage(short=f"占 {human(info['合计'])}", line=line, detail=detail)
