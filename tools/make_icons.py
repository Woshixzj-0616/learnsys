# -*- coding: utf-8 -*-
"""把 `learnsys/ask/icon.py::pixmap()` 这一个画法导出成所有图标文件。

用法：
    .venv\\Scripts\\python.exe tools\\make_icons.py          # 生成
    .venv\\Scripts\\python.exe tools\\make_icons.py --check  # 只校验，不写文件

产物：
    ｜学习工作台.ico                      多尺寸（16…256），exe / 快捷方式 / favicon
    ｜web/icons/icon-192.png              PWA 普通图标
    ｜web/icons/icon-512.png
    ｜web/icons/icon-maskable-512.png     全出血 + 安全区
    ｜web/icons/apple-touch-icon.png      180，全出血（iOS 自己切圆角）
    ｜build/icon-preview-1024.png         人工目检用，不入发布包
"""
from __future__ import annotations

import argparse
import os
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# QPixmap 需要一个 QGuiApplication；在无桌面的构建环境里走 offscreen。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui  # noqa: E402

from learnsys import config  # noqa: E402
from learnsys.ask import icon  # noqa: E402

PNG_TARGETS = (
    ("web/icons/icon-192.png", 192, False),
    ("web/icons/icon-512.png", 512, False),
    ("web/icons/icon-maskable-512.png", 512, True),
    ("web/icons/apple-touch-icon.png", 180, True),
)
PREVIEW = ("build/icon-preview-1024.png", 1024, False)


def _app() -> QtGui.QGuiApplication:
    app = QtGui.QGuiApplication.instance()
    return app or QtGui.QGuiApplication([])


def _png_size(path: pathlib.Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} 不是 PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _ico_sizes(path: pathlib.Path) -> list[int]:
    data = path.read_bytes()
    if len(data) < 6:
        raise ValueError(f"{path} 太小，不是 ICO")
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    if reserved != 0 or kind != 1:
        raise ValueError(f"{path} 不是图标集")
    sizes = []
    for index in range(count):
        offset = 6 + index * 16
        edge = data[offset]
        sizes.append(256 if edge == 0 else edge)
    return sizes


def check() -> int:
    problems = []
    ico = config.ICON_PATH
    if not ico.exists():
        problems.append(f"缺少 {ico}")
    else:
        try:
            sizes = _ico_sizes(ico)
            expected = list(icon.SIZES)
            if sizes != expected:
                problems.append(f"{ico.name} 尺寸是 {sizes}，期望 {expected}")
        except Exception as exc:
            problems.append(str(exc))
    for rel, size, _maskable in PNG_TARGETS:
        path = ROOT / rel
        if not path.exists():
            problems.append(f"缺少 {rel}")
            continue
        try:
            width, height = _png_size(path)
            if (width, height) != (size, size):
                problems.append(f"{rel} 是 {width}x{height}，期望 {size}x{size}")
        except Exception as exc:
            problems.append(str(exc))
    preview = ROOT / PREVIEW[0]
    if not preview.exists():
        problems.append(f"缺少 {PREVIEW[0]}")
    if problems:
        print("图标检查失败：")
        for item in problems:
            print("  -", item)
        return 1
    print(f"图标检查通过：ICO {len(icon.SIZES)} 档 + {len(PNG_TARGETS)} 张 PNG + 预览图")
    return 0


def generate() -> int:
    _app()
    ico = icon.write_ico(config.ICON_PATH, force=True)
    if ico is None:
        print(f"生成 {config.ICON_PATH.name} 失败")
        return 1
    for rel, size, maskable in PNG_TARGETS:
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not icon.pixmap(size, maskable=maskable).save(str(path), "PNG"):
            print(f"生成 {rel} 失败")
            return 1
    preview_path = ROOT / PREVIEW[0]
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    if not icon.pixmap(PREVIEW[1]).save(str(preview_path), "PNG"):
        print(f"生成 {PREVIEW[0]} 失败")
        return 1
    print(f"图标已生成：{ico}")
    for rel, _size, _maskable in PNG_TARGETS:
        print("  ", rel)
    print("  ", PREVIEW[0])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生成/校验学习工作台图标")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args()
    return check() if args.check else generate()


if __name__ == "__main__":
    raise SystemExit(main())
