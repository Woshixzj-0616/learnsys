"""模块注册表与前端资源路径（源码 / PyInstaller 打包后都指向同一份）。"""
from __future__ import annotations

import json
import pathlib
import sys

from learnsys import config


def _base() -> pathlib.Path:
    # PyInstaller 把数据解到 _MEIPASS；源码运行时就是仓库根
    return pathlib.Path(getattr(sys, "_MEIPASS", config.ROOT))


def web_dir() -> pathlib.Path:
    return _base() / "web"


def registry_path() -> pathlib.Path:
    return _base() / "learnsys" / "modules" / "registry.json"


def load_registry() -> dict:
    """读注册表；读坏了返回空列表 —— 壳层会显示「没有模块」，但不白屏。"""
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except Exception:
        return {"modules": []}
    modules = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(modules, list):
        return {"modules": []}
    return {"modules": sorted(
        [m for m in modules if isinstance(m, dict) and m.get("id")],
        key=lambda m: (int(m.get("order") or 999), str(m.get("id"))))}
