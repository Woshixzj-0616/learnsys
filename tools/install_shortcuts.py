# -*- coding: utf-8 -*-
"""安装「学习工作台」的桌面 / 开始菜单 / 开机自启快捷方式。

用法（打包完之后跑）：
    .venv\\Scripts\\python.exe tools\\install_shortcuts.py
    .venv\\Scripts\\python.exe tools\\install_shortcuts.py --target path\\to\\学习工作台.exe

只创建三个入口，不碰任务栏固定项：
  · 桌面        学习工作台.lnk            正常启动（起后台 + 横栏 + 打开工作台）
  · 开始菜单    学习工作台.lnk            同上（app 自己启动时也会补这一条）
  · Startup     学习工作台.lnk --background  开机只起后台 + 横栏
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, product  # noqa: E402
from learnsys.ask import shortcuts  # noqa: E402

DEFAULT_EXE = ROOT / "dist" / product.PRODUCT_NAME / product.EXE_NAME


def main() -> int:
    parser = argparse.ArgumentParser(description="安装学习工作台快捷方式")
    parser.add_argument("--target", default=str(DEFAULT_EXE), help="学习工作台.exe 路径")
    parser.add_argument("--icon", default=str(config.ICON_PATH), help="图标路径")
    parser.add_argument("--no-startup", action="store_true", help="不装开机自启")
    args = parser.parse_args()

    target = pathlib.Path(args.target)
    icon = pathlib.Path(args.icon)
    if not target.exists():
        print(f"找不到可执行文件：{target}")
        print("先运行 打包.cmd，或用 --target 指向已有的 exe。")
        return 1
    if not icon.exists():
        print(f"找不到图标：{icon}（先运行 tools\\make_icons.py）")
        return 1

    made = []
    desktop = shortcuts.make_shortcut(
        shortcuts.desktop_dir() / product.LNK_NAME, target, icon)
    if desktop:
        made.append(("桌面", desktop))
    start_menu = shortcuts.make_start_menu_shortcut(target, icon)
    if start_menu:
        made.append(("开始菜单", start_menu))
    if not args.no_startup:
        startup = shortcuts.make_startup_shortcut(
            target, icon, arguments="--background", working_dir=target.parent)
        if startup:
            made.append(("开机自启", startup))

    shortcuts.notify_shell_changed(icon, target, *[path for _, path in made])
    if not made:
        print("没有创建成功 —— 检查 comtypes 是否可用。")
        return 1
    for label, path in made:
        print(f"{label}: {path}")
    print("完成。任务栏不固定任何项；打开工作台请用桌面/开始菜单的「学习工作台」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
