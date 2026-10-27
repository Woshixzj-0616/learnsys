"""工作目录白名单：派活只能读用户明确允许的目录。"""
from __future__ import annotations

import pathlib

from learnsys import config as app_config

SYSTEM_ROOTS = (
    pathlib.Path(r"C:\Windows"),
    pathlib.Path(r"C:\Program Files"),
    pathlib.Path(r"C:\Program Files (x86)"),
    pathlib.Path(r"C:\ProgramData"),
)


def _within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def allowed_roots(settings: dict | None = None) -> list[pathlib.Path]:
    raw = (settings or {}).get("allowed_roots")
    roots: list[pathlib.Path] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            text = str(item or "").strip()
            if not text:
                continue
            try:
                path = pathlib.Path(text).expanduser().resolve()
            except (OSError, ValueError):
                continue
            if path.is_dir():
                roots.append(path)
    if not roots:
        roots = [pathlib.Path(app_config.DATA_ROOT).resolve()]
    return roots


def default_workspace(settings: dict | None = None) -> pathlib.Path:
    return allowed_roots(settings)[0]


def resolve_workspace(raw: str = "",
                      settings: dict | None = None) -> tuple[pathlib.Path | None, str]:
    """返回 (目录, 错误中文)；空目录 = 白名单第一个。"""
    text = str(raw or "").strip()
    if text.startswith("\\\\"):
        return None, "不支持网络路径（UNC），请选本机目录。"
    path = pathlib.Path(text).expanduser() if text else default_workspace(settings)
    try:
        path = path.resolve()
    except (OSError, ValueError) as exc:
        return None, f"这个目录读不了：{exc}"
    if not path.is_dir():
        return None, "工作目录不存在，或者不是文件夹。"
    roots = allowed_roots(settings)
    if not any(_within(path, root) for root in roots):
        shown = "、".join(str(root) for root in roots)
        return None, f"这个目录不在允许列表里。允许的目录：{shown}"
    for system in SYSTEM_ROOTS:
        try:
            if _within(path, system.resolve()):
                return None, "不能选 Windows 系统目录。"
        except OSError:
            continue
    return path, ""
