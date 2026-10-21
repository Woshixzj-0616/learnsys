"""插件清单与前端资源路径（源码 / PyInstaller 打包后都指向同一份）。

v2 P5 起，学习系统把每个功能都当成插件：一个插件 = `learnsys/plugins/<id>/plugin.json`
加它自己的入口（原生页 / iframe / 外部 URL）。前端只认 `/api/modules` 返回的清单，
加插件不用改壳层代码。

旧版单文件 `learnsys/modules/registry.json` 仍作为兜底读取（老 exe / 老分支），
但源码里已经不再维护它 —— 清单只有插件目录这一份。
"""
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


def plugins_dir() -> pathlib.Path:
    return _base() / "learnsys" / "plugins"


def registry_path() -> pathlib.Path:
    """旧的单文件清单路径（仅兜底；源码里已不存在）。"""
    return _base() / "learnsys" / "modules" / "registry.json"


def _sort_key(module: dict) -> tuple[int, str]:
    try:
        order = int(module.get("order") or 999)
    except (TypeError, ValueError):
        order = 999
    return order, str(module.get("id") or "")


def _read_manifest(path: pathlib.Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    data.setdefault("status", "ready")
    data.setdefault("version", "2.3.0")
    data.setdefault("category", "其他")
    data.setdefault("home", False)
    return data


def load_registry() -> dict:
    """读插件目录；插件目录不存在时退回旧的 registry.json。读坏了返回空清单，不白屏。"""
    modules: list[dict] = []
    root = plugins_dir()
    if root.is_dir():
        for path in sorted(root.glob("*/plugin.json")):
            item = _read_manifest(path)
            if item is not None:
                item["plugin_path"] = str(path.parent.name)
                modules.append(item)
    else:
        legacy = registry_path()
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        raw = data.get("modules") if isinstance(data, dict) else None
        if isinstance(raw, list):
            modules = [m for m in raw if isinstance(m, dict) and m.get("id")]
    return {"schema": 2, "modules": sorted(modules, key=_sort_key)}
