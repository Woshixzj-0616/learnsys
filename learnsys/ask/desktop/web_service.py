"""本地服务与版本检查：起后台、打开工作台、开机入口维护。"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys
import traceback
import urllib.request

from PySide6 import QtGui

from learnsys import config, product
from learnsys.ask import icon as icon_mod, shortcuts, workbench
from learnsys.ask.desktop import deep_link
from learnsys.product import VERSION


def _server_info(port: int, timeout: float = 0.5) -> dict:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _server_healthy(port: int, timeout: float = 0.5) -> bool:
    """端口上是不是已经有一个能用的学习工作台后台（避免重复起、也避免误杀别人）。"""
    return bool(_server_info(port, timeout).get("ok"))


def _server_has_ui(port: int, timeout: float = 0.5) -> bool:
    """这个后台是不是接在 Qt 主进程上（能调快捷栏），而不是单独起的开发后台。"""
    return bool(_server_info(port, timeout).get("quickbar"))


def version_line() -> str:
    """给托盘 / 启动提示用的一行版本：打包后带打包日期，源码跑就标「源码」。"""
    if config.FROZEN:
        try:
            day = datetime.date.fromtimestamp(pathlib.Path(sys.executable).stat().st_mtime)
            return f"v{VERSION}（{day.year}-{day.month:02d}-{day.day:02d} 打包）"
        except OSError:
            return f"v{VERSION}"
    return f"v{VERSION}（源码运行）"


def newest_source_mtime(src_dir: pathlib.Path) -> float | None:
    """目录里 *.py 的最新修改时间；目录不存在（exe 被拷去别处了）返回 None。"""
    if not src_dir.is_dir():
        return None
    newest = 0.0
    for p in src_dir.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    return newest or None


def launcher_target() -> pathlib.Path:
    """「学习工作台」是怎么被起来的：**打包后 = 它自己的 exe**；源码跑 = 项目里那个 .cmd。"""
    if config.FROZEN:
        return pathlib.Path(sys.executable).resolve()
    return config.ROOT / product.LAUNCHER_NAME


def _silence_windowed() -> None:
    """打包成「没有黑框」之后 stdout / stderr 是 None —— 兜个黑洞，免得哪句 print 把程序炸了。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass


def watchdog_command() -> str:
    """后台守护的计划任务每分钟跑这一条。"""
    if config.FROZEN:
        return f'"{launcher_target()}" --watchdog'
    return f'"{config.ROOT / product.LAUNCHER_NAME}" --watchdog'


def _pythonw() -> str:
    """挑一个不弹黑框的解释器（跟 学习工作台.cmd 同一个顺序）。"""
    for candidate in (config.ROOT / ".venv" / "Scripts" / "pythonw.exe",
                      pathlib.Path(r"D:\Desktop\bilinote\asr-venv\Scripts\pythonw.exe"),
                      pathlib.Path(r"D:\python\pythonw.exe")):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _tray_icon() -> QtGui.QIcon:
    """托盘 / 窗口 / 任务栏共用那一张 —— 画法只在 learnsys/ask/icon.py 一处。"""
    return icon_mod.icon()


def check_new_version(timeout: float = 4.0) -> str | None:
    """查 GitHub 最新 release，比当前新就返回版本号；网络/解析失败一律静默。"""
    import json as _json
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/Woshixzj-0616/learnsys/releases/latest",
            headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            tag = str(_json.loads(resp.read().decode("utf-8")).get("tag_name") or "")
    except Exception:
        return None
    def nums(t: str) -> tuple:
        parts = [p for p in t.lower().lstrip("v").split(".") if p.isdigit()]
        return tuple(int(x) for x in parts) or (0,)
    return tag if nums(tag) > nums(VERSION) else None

class WebServiceMixin:
    def start_web(self) -> None:
        """起本地服务（Agent / 数据 / 六级分析共用一个进程）。

        顺序：8765 已有健康后台就复用 → 否则自己起 8765 → 被占就退 8766。
        失败不拦启动 —— 快捷栏仍然能用。
        """
        if self._web_port:
            return
        try:
            from learnsys.server.app import port_free, serve_in_thread
        except Exception as exc:
            self._log_startup_error(exc)
            self._warn(f"本地服务没加载起来：{exc}")
            return

        last_error = ""
        for port in (8765, 8766):
            if _server_healthy(port):
                if _server_has_ui(port):
                    self._web_port = port
                    self._web_external = True
                    self.bar.show_message(f"{product.PRODUCT_NAME}后台已在运行：http://127.0.0.1:{port}/")
                    return
                # 单独起的开发后台：数据能用，但页面调不动快捷栏 → 另起一个带 UI 的
                last_error = f"端口 {port} 有一个没接快捷栏的后台"
                continue
            if not port_free(port):
                last_error = f"端口 {port} 被别的程序占着"
                continue
            try:
                self._web_server = serve_in_thread(port)
                self._web_port = port
                self.bar.show_message(f"{product.PRODUCT_NAME}后台已启动：http://127.0.0.1:{port}/")
                return
            except Exception as exc:
                last_error = str(exc)
                self._log_startup_error(exc)
        self._warn(f"本地服务没起来：{last_error or '8765 / 8766 都不可用'}")

    @staticmethod
    def _log_startup_error(exc: BaseException) -> None:
        """无黑框模式看不到 traceback —— 落到数据目录，用户能直接把文件发过来。"""
        try:
            path = config.DATA_ROOT / "启动错误.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
                fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        except Exception:
            pass

    def web_url(self) -> str:
        return f"http://127.0.0.1:{self._web_port}/" if self._web_port else ""

    def open_web(self) -> None:
        """打开学习工作台：有窗口就聚焦，没有就开一个无地址栏的应用窗口。"""
        if not self._web_port:
            self.start_web()
        if not self._web_port:
            self._warn(f"{product.PRODUCT_NAME}打不开：本地服务没起来。")
            return
        self.bar.show_message(f"正在打开{product.PRODUCT_NAME}：http://127.0.0.1:{self._web_port}/")
        # 默认入口语义：窗口已经开在别的页，也通过深链桥叫回 #/today。
        # 新窗口本来就从根路径落到 today，这条请求不会改变结果。
        deep_link.post_navigate(self._web_port, "#/today")
        how = workbench.open_or_focus(self.web_url())
        if how == "默认浏览器":
            self._warn(f"没找到 Edge / Chrome，已改用默认浏览器打开{product.PRODUCT_NAME}。")

    def _install_shortcuts(self) -> None:
        """开始菜单入口收尾：补「学习工作台」快捷方式 + 清旧版残留。"""
        icon_path = icon_mod.ensure_ico()
        if icon_path is None:
            return
        if shortcuts.install(launcher_target(), icon_path)["shortcut"] is None:
            print("开始菜单快捷方式没摆上 —— 可以手动从桌面快捷方式启动", file=sys.stderr)

    def _called_back(self, mode: str = "show") -> None:
        """又点了一次「学习工作台」—— 正常调用：横栏露出来，工作台也打开/聚焦。

        Startup 的 --background 调用只保持后台，不抢焦点。
        """
        if mode == "background":
            return
        self.show_bar()
        self.open_web()
        self.bar.show_message(f"{product.PRODUCT_NAME}已经在跑了 —— 横栏和工作台都给你叫回来了。")
