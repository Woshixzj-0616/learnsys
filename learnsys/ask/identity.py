"""给「问一问」一个自己的 Windows 身份（AppUserModelID）。

不声明身份时，Windows 只能按 exe（pythonw.exe）去找「注册过这个 exe 的应用」——
第一个撞上的是 IDLE，于是「固定到任务栏」固定出来的就成了「IDLE shell」。

这里三件事（都是幂等的，启动跑一遍即可）：
① 本进程声明自己的 AUMID —— **必须在建任何窗口之前调**；
② 在 HKCU 注册这个 AUMID 的显示名 / 图标 / 「重新启动」命令；
③ 在开始菜单放一个同名快捷方式 —— 固定到任务栏的可靠入口。
"""
from __future__ import annotations

import os
import pathlib
import winreg

AUMID = "Xzj.XueXi.WenYiWen.1"        # 只属于「问一问」的身份，别改（改了等于换一个 app）
DISPLAY_NAME = "问一问"
DESCRIPTION = "问一问 · 框选屏幕问 AI"
LNK_NAME = "问一问.lnk"
KEY = r"Software" + chr(92) + "Classes" + chr(92) + "AppUserModelId" + chr(92) + AUMID

PIN_HELP = ("固定到任务栏：在横栏的任务栏按钮上右键 →「固定到任务栏」。\n"
            "图标还是 Python / 点了打不开 → 托盘右键「修复任务栏固定」（它会顺手让 Explorer 重读图标）。\n"
            "名字还叫「Python」的那条：名字是第一次固定时烙进去的、程序改不掉 ⇒ 右键它 →「从任务栏取消固定」，"
            "再到开始菜单搜「问一问」→ 右键 →「固定到任务栏」。")

# 打包成「问一问.exe」之后就不用再解释 Python 那些事了 —— 固定出来本来就是对的
PIN_HELP_FROZEN = ("固定到任务栏：在横栏的任务栏按钮上右键 →「固定到任务栏」。\n"
                   "（这一版固定出来就叫「问一问」、带自己的图标 —— 不会再变成 Python）。\n"
                   "要是那条固定点着没反应（还指着旧的 pythonw.exe）→ 托盘右键「修复任务栏固定」。")

SHCNE_UPDATEITEM = 0x00002000
SHCNF_PATHW = 0x0005
SHCNF_FLUSH = 0x1000


def notify_shell_changed(*paths: object) -> None:
    """告诉 Explorer「这些文件（快捷方式 / 图标）变了，重读一下」。

    少了这一步，任务栏会一直挂着**建固定时**的旧图标 —— 看着像「换了图标没用」。
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


def declare_process_identity() -> bool:
    """让本进程用「问一问」的身份（要在建窗口之前调，不然没效果）。"""
    try:
        import ctypes
        return ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID) == 0
    except Exception:
        return False


def register(icon_path: pathlib.Path, launcher: pathlib.Path) -> bool:
    """把身份写进 HKCU：任务栏按钮上的名字 / 图标，以及「点了它该跑什么」。"""
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_WRITE)
    except OSError:
        return False
    try:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, DISPLAY_NAME)
        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_path))
        winreg.SetValueEx(key, "RelaunchCommand", 0, winreg.REG_SZ, chr(34) + str(launcher) + chr(34))
        winreg.SetValueEx(key, "RelaunchDisplayNameResource", 0, winreg.REG_SZ, DISPLAY_NAME)
        winreg.SetValueEx(key, "RelaunchIconResource", 0, winreg.REG_SZ, str(icon_path))
        return True
    except OSError:
        return False
    finally:
        key.Close()


def start_menu_dir() -> pathlib.Path:
    """当前用户的「开始菜单 → 程序」目录。"""
    base = os.environ.get("APPDATA") or str(pathlib.Path.home() / "AppData" / "Roaming")
    return pathlib.Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def make_shortcut(launcher: pathlib.Path, icon_path: pathlib.Path) -> pathlib.Path | None:
    """开始菜单里摆一个「问一问」（右键它就能固定到任务栏）。

    走 IShellLinkW 这条正经接口：comtypes 下的 WScript.Shell 是裸 IDispatch，
    属性赋值会静默丢掉、连 Save 都没有（踩过）。
    """
    lnk = start_menu_dir() / LNK_NAME
    try:
        import comtypes.client
        import comtypes.shelllink as shelllink
        from comtypes.persist import IPersistFile
        link = comtypes.client.CreateObject(shelllink.ShellLink,
                                            interface=shelllink.IShellLinkW)
        link.SetPath(str(launcher))
        link.SetWorkingDirectory(str(launcher.parent))
        link.SetIconLocation(str(icon_path), 0)
        link.SetDescription(DESCRIPTION)
        link.QueryInterface(IPersistFile).Save(str(lnk), True)
        return lnk if lnk.exists() else None
    except Exception:
        return None


def install(launcher: pathlib.Path, icon_path: pathlib.Path) -> dict:
    """启动时跑一遍：注册身份 + 摆好开始菜单快捷方式。坏了也不影响主流程。"""
    shortcut = make_shortcut(launcher, icon_path)
    notify_shell_changed(shortcut, icon_path, launcher)
    return {"registered": register(icon_path, launcher),
            "shortcut": shortcut}


def taskbar_dir() -> pathlib.Path:
    """任务栏「已固定」那堆快捷方式放的地方（系统自己的目录）。"""
    base = os.environ.get("APPDATA") or str(pathlib.Path.home() / "AppData" / "Roaming")
    return (pathlib.Path(base) / "Microsoft" / "Internet Explorer" / "Quick Launch"
            / "User Pinned" / "TaskBar")


def carry_identity(lnk: pathlib.Path) -> bool:
    """这条快捷方式是不是「挂在我们 AUMID 上」的（拿字节找就行，不用解 .lnk 格式）。"""
    try:
        return AUMID.encode("utf-16le") in lnk.read_bytes()
    except OSError:
        return False


def repair_taskbar_pins(launcher: pathlib.Path, icon_path: pathlib.Path) -> int:
    """把任务栏上「挂在咱 AUMID、却指着裸 pythonw.exe」的固定改回指着问一问.cmd。

    Windows 自己固定时只抄得到 exe，抄不到命令行 ⇒ 那条固定点了没反应；
    重新 Load 再 Save 能把它自带的身份（AUMID）原样留着。
    """
    fixed = 0
    touched = []
    for lnk in sorted(taskbar_dir().glob("*.lnk")):
        if not carry_identity(lnk):
            continue
        try:
            import comtypes.client
            import comtypes.shelllink as shelllink
            from comtypes.persist import IPersistFile
            link = comtypes.client.CreateObject(shelllink.ShellLink,
                                                interface=shelllink.IShellLinkW)
            store = link.QueryInterface(IPersistFile)
            store.Load(str(lnk), 0)
            link.SetPath(str(launcher))
            link.SetArguments("")
            link.SetWorkingDirectory(str(launcher.parent))
            link.SetIconLocation(str(icon_path), 0)
            link.SetDescription(DESCRIPTION)
            store.Save(str(lnk), True)
            fixed += 1
            touched.append(lnk)
        except Exception:
            continue
    if touched:
        # 改完 .lnk 还不够 —— 得让 Explorer 重读，否则任务栏还显示建固定时的旧图标
        notify_shell_changed(*touched, icon_path, launcher)
    return fixed
