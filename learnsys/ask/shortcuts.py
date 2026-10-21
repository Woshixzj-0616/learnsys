"""快捷方式：开始菜单 / 开机自启 / 桌面。

产品已经不再需要 Windows 的 AppUserModelID：横栏是 Qt.Tool，不进任务栏；
唯一入口是用户手动点「学习工作台」快捷方式。这里只做三件幂等的小事：
① 在开始菜单放一个「学习工作台」快捷方式（缺了才补）；
② 清理旧版留下的「问一问」开始菜单项和旧 AUMID 注册键；
③ 提供创建 Startup（带 `--background`）和桌面快捷方式的公共函数。
"""
from __future__ import annotations

import os
import pathlib
import winreg

from learnsys import product

# 旧版身份：只用于迁移清理，不再注册。
LEGACY_AUMID = product.LEGACY_AUMID
LEGACY_START_MENU = "问一问.lnk"
LEGACY_KEY = (r"Software" + chr(92) + "Classes" + chr(92) + "AppUserModelId"
              + chr(92) + LEGACY_AUMID)

SHCNE_UPDATEITEM = 0x00002000
SHCNF_PATHW = 0x0005
SHCNF_FLUSH = 0x1000


def notify_shell_changed(*paths: object) -> None:
    """告诉 Explorer「这些文件（快捷方式 / 图标）变了，重读一下」。

    少了这一步，开始菜单/任务栏会一直挂着旧图标 —— 看着像「换了图标没用」。
    """
    try:
        import ctypes
        shell32 = ctypes.WinDLL("shell32")
        shell32.SHChangeNotify.argtypes = [ctypes.c_long, ctypes.c_uint,
                                           ctypes.c_wchar_p, ctypes.c_wchar_p]
        shell32.SHChangeNotify.restype = None
        for path in paths:
            if path:
                shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSH,
                                       str(path), None)
    except Exception:
        pass


def _appdata() -> pathlib.Path:
    base = os.environ.get("APPDATA") or str(pathlib.Path.home() / "AppData" / "Roaming")
    return pathlib.Path(base)


def start_menu_dir() -> pathlib.Path:
    """当前用户的「开始菜单 → 程序」目录。"""
    return _appdata() / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def startup_dir() -> pathlib.Path:
    """开机自启目录。"""
    return start_menu_dir() / "Startup"


def desktop_dir() -> pathlib.Path:
    """当前用户的桌面（优先读注册表里被重定向过的 Desktop，读不到退回 ~/Desktop）。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software" + chr(92) + "Microsoft" + chr(92)
                             + "Windows" + chr(92) + "CurrentVersion"
                             + chr(92) + "Explorer" + chr(92) + "User Shell Folders")
        try:
            value = winreg.QueryValueEx(key, "Desktop")[0]
        finally:
            key.Close()
        expanded = os.path.expandvars(value)
        path = pathlib.Path(expanded)
        if path.exists():
            return path
    except OSError:
        pass
    return pathlib.Path.home() / "Desktop"


def make_shortcut(lnk: pathlib.Path, target: pathlib.Path,
                  icon_path: pathlib.Path | None = None, *,
                  arguments: str = "",
                  working_dir: pathlib.Path | None = None,
                  description: str = product.DESCRIPTION) -> pathlib.Path | None:
    """用一个正经的 IShellLinkW 写 .lnk（WScript.Shell 会静默丢属性，踩过）。"""
    lnk.parent.mkdir(parents=True, exist_ok=True)
    try:
        import comtypes.client
        import comtypes.shelllink as shelllink
        from comtypes.persist import IPersistFile
        link = comtypes.client.CreateObject(shelllink.ShellLink,
                                            interface=shelllink.IShellLinkW)
        link.SetPath(str(target))
        if arguments:
            link.SetArguments(arguments)
        link.SetWorkingDirectory(str(working_dir or target.parent))
        if icon_path is not None:
            link.SetIconLocation(str(icon_path), 0)
        link.SetDescription(description)
        link.QueryInterface(IPersistFile).Save(str(lnk), True)
        return lnk if lnk.exists() else None
    except Exception:
        return None


def make_start_menu_shortcut(target: pathlib.Path, icon_path: pathlib.Path) -> pathlib.Path | None:
    lnk = start_menu_dir() / product.LNK_NAME
    return make_shortcut(lnk, target, icon_path)


def make_startup_shortcut(target: pathlib.Path, icon_path: pathlib.Path, *,
                          arguments: str, working_dir: pathlib.Path | None = None
                          ) -> pathlib.Path | None:
    """Startup 里放「学习工作台」，参数固定带 --background。"""
    lnk = startup_dir() / product.STARTUP_LNK_NAME
    return make_shortcut(lnk, target, icon_path, arguments=arguments,
                         working_dir=working_dir)


def remove_legacy() -> None:
    """一次性清理旧版：开始菜单「问一问.lnk」+ 旧 AUMID 注册键。幂等。"""
    legacy = start_menu_dir() / LEGACY_START_MENU
    try:
        if legacy.exists():
            legacy.unlink()
            notify_shell_changed(legacy)
    except OSError:
        pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, LEGACY_KEY)
    except OSError:
        pass


def install(target: pathlib.Path, icon_path: pathlib.Path) -> dict:
    """启动时跑一遍：补开始菜单快捷方式 + 清旧项。坏了也不影响主流程。"""
    remove_legacy()
    shortcut = make_start_menu_shortcut(target, icon_path)
    notify_shell_changed(shortcut, icon_path, target)
    return {"shortcut": shortcut}
