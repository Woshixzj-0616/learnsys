"""工作台浏览器进程管理：独立 profile、随机 CDP 端口、只记录 URL/标题/域名。

安全边界（与施工单 P20.2 一致）：
- 只用自己启动的 profile（`<数据目录>/浏览器配置`），绝不碰用户默认 profile；
- 调试端口随机、只绑 127.0.0.1，端口/PID/profile 路径不返回前端；
- 只调用 CDP 的 `/json/list`、`/json/new`、`/json/close` 三个 HTTP 端点；
- 关闭时只终止自己 Popen 的 PID，并校验命令行里包含本 profile 路径。
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import threading
import time

from learnsys import config, store
from learnsys.ask.workbench import find_browser

from . import cdp, urls

LAUNCH_WAIT_SECONDS = 8.0
POLL_SECONDS = 2.0
_CREATE_NO_WINDOW = 0x08000000


def launch_args(profile: pathlib.Path, download_dir: pathlib.Path,
                browser: str = "msedge.exe", url: str | None = None) -> list[str]:
    """启动参数：必须保留地址栏（不用 `--app=`），随机调试端口。"""
    args = [
        str(browser),
        f"--user-data-dir={profile}",
        "--remote-debugging-port=0",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-features=Translate,MediaRouter,OptimizationHints",
        f"--download-directory={download_dir}",
    ]
    if url:
        args += ["--new-window", str(url)]
    return args


def _command_line(pid: int) -> str:
    """取进程命令行（用于确认 PID 还是我们启动的那个浏览器）；取不到返回空串。"""
    if os.name != "nt":
        return ""
    commands = [
        ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/value"],
        ["powershell", "-NoProfile", "-Command",
         f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=4, creationflags=_CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            continue
        output = (result.stdout or "").strip()
        if output:
            return output
    return ""


def _pid_on_port(port: int) -> int | None:
    """查本机哪个 PID 在监听这个调试端口（只用于「接管残留实例」后的关闭）。"""
    if os.name != "nt" or not port:
        return None
    try:
        result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=5,
                                creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    needle = f":{int(port)}"
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if (len(parts) >= 5 and parts[1].endswith(needle)
                and parts[3].upper() == "LISTENING"):
            try:
                return int(parts[4])
            except ValueError:
                continue
    return None


class BrowserManager:
    """一个进程一份单例；`get_manager()` 管全局实例。"""

    def __init__(self, data_root: pathlib.Path | None = None,
                 browser_path: str | None = None, popen=None):
        self.data_root = pathlib.Path(data_root or config.DATA_ROOT)
        self.profile = self.data_root / "浏览器配置"
        self.downloads = self.data_root / "浏览器下载"
        self._browser_path = browser_path
        self._popen = popen or subprocess.Popen
        self._proc = None
        self._port: int | None = None
        self._tabs: dict[str, dict] = {}
        # 每个 tab 上一次看到的 (url, title)。**暂停记录时也更新** ——
        # 这样「暂停期间打开、恢复后标签还开着」的页面不会被补记进库。
        self._seen: dict[str, tuple[str, str]] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._message = "还没启动"
        self._started_at = 0.0

    # ---- 状态 ----

    def browser_executable(self) -> str | None:
        if self._browser_path:
            return self._browser_path
        found = find_browser()
        if found:
            self._browser_path = found
        return found

    def _alive(self) -> bool:
        # 以 CDP 端口为准，不看 Popen 的 poll：已经有同 profile 实例时，
        # 新起的 launcher 进程会立刻退出，但浏览器其实活着。
        if not self._port:
            return False
        return cdp.version_ok(self._port)

    def status(self) -> dict:
        settings = config.browser_settings()
        running = self._alive()
        tabs = []
        if running and settings["record"]:
            tabs = [dict(tab) for tab in list(self._tabs.values())[:20]]
        return {
            "enabled": settings["enabled"],
            "running": running,
            "record": settings["record"],
            "paused": running and not settings["record"],
            "current": tabs[0] if tabs else None,
            "tabs": tabs,
            "message": ("运行中" if running else self._message),
        }

    # ---- 启动 / 复用 / 关闭 ----

    def _clear_stale_lock(self) -> None:
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                (self.profile / name).unlink()
            except OSError:
                pass

    def _expire_history(self) -> None:
        try:
            conn = store.connect()
            try:
                store.cleanup_browser_events(
                    conn, config.browser_settings()["history_days"])
            finally:
                conn.close()
        except Exception:
            pass

    def _wait_for_port(self, proc, timeout: float = LAUNCH_WAIT_SECONDS) -> int | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # 先看端口：已有实例时新起的进程会立刻退出（单例转发），
            # 这时照样能用残留实例的调试端口。
            port = cdp.read_devtools_port(self.profile)
            if port and cdp.version_ok(port):
                return port
            if proc is not None and proc.poll() is not None:
                return None
            time.sleep(0.1)
        return None

    def launch(self) -> dict:
        settings = config.browser_settings()
        if not settings["enabled"]:
            self._message = "浏览器功能已关闭"
            return self.status()
        with self._lock:
            if self._alive():
                return self.status()
            browser = self.browser_executable()
            if not browser:
                self._message = "没找到 Edge 或 Chrome，先装一个再试"
                return self.status()
            # 后台重启过、浏览器还活着（close_on_exit=false 或上次崩溃）：直接接管。
            existing = cdp.read_devtools_port(self.profile)
            if existing and cdp.version_ok(existing):
                self._port = existing
                self._proc = None
                self._seen = {}
                self._message = "复用了已运行的工作台浏览器"
                self._start_polling()
                return self.status()
            try:
                self.profile.mkdir(parents=True, exist_ok=True)
                self.downloads.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._message = f"浏览器目录建不出来：{exc}"
                return self.status()
            if self._proc is not None and self._proc.poll() is not None:
                self._proc = None
                self._port = None
            self._expire_history()
            self._clear_stale_lock()
            self._seen = {}
            args = launch_args(self.profile, self.downloads, browser)
            try:
                self._proc = self._popen(args, close_fds=True)
            except OSError as exc:
                self._message = f"浏览器没启动：{exc}"
                return self.status()
            port = self._wait_for_port(self._proc)
            if not port:
                self._terminate_own()
                self._message = "浏览器没有在 8 秒内启动（可能被安全软件拦住了）"
                return self.status()
            self._port = port
            self._started_at = time.time()
            self._message = "已启动工作台浏览器"
            self._start_polling()
            return self.status()

    def _start_polling(self) -> None:
        self._stop.clear()
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._poll_loop,
                                        name="learnsys-browser", daemon=True)
        self._thread.start()

    def open_url(self, url: str) -> dict:
        """校验后在新标签打开；浏览器没开就先启动。返回中文 message。"""
        try:
            normalized = urls.normalize_url(url)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        settings = config.browser_settings()
        if not settings["enabled"]:
            return {"ok": False, "message": "没有打开：浏览器功能已关闭。",
                    "url": normalized}
        if not self._alive():
            launched = self.launch()
            if not launched.get("running"):
                return {"ok": False,
                        "message": f"没有打开：{launched.get('message') or '浏览器没启动'}。",
                        "url": normalized}
        try:
            cdp.new_tab(self._port, normalized)
        except cdp.CdpError:
            # 新版 Chromium 的 PUT 不被接受 / 端口短暂不可用：让浏览器单例自己接管。
            browser = self.browser_executable()
            if not browser:
                return {"ok": False, "message": "没有打开：没找到浏览器。",
                        "url": normalized}
            try:
                self._popen([browser, f"--user-data-dir={self.profile}", normalized],
                            close_fds=True)
            except OSError as exc:
                return {"ok": False, "message": f"没有打开：{exc}",
                        "url": normalized}
        return {"ok": True, "message": f"已打开：{normalized}", "url": normalized}

    def close(self, *, force: bool = True) -> dict:
        """关闭自己启动的浏览器。force=False 时只按 `close_on_exit` 决定。"""
        with self._lock:
            if not force and not config.browser_settings()["close_on_exit"]:
                return self.status()
            self._stop.set()
            thread = self._thread
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
            self._thread = None
            proc = self._proc
            if proc is not None and proc.poll() is None:
                if self._owns_pid(proc.pid):
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            elif self._port:
                # 接管来的实例没有 Popen：用监听端口反查 PID，仍校验 profile 再杀。
                pid = _pid_on_port(self._port)
                if pid and self._owns_pid(pid):
                    try:
                        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                       capture_output=True, timeout=8,
                                       creationflags=_CREATE_NO_WINDOW)
                    except (OSError, subprocess.SubprocessError):
                        pass
            self._proc = None
            self._port = None
            self._tabs = {}
            self._seen = {}
            self._message = "已关闭"
            return self.status()

    def shutdown(self) -> None:
        """后台退出时调用；`close_on_exit=false` 就保留浏览器。"""
        try:
            self.close(force=False)
        except Exception:
            pass

    def _owns_pid(self, pid: int) -> bool:
        """校验 PID 的命令行包含本 profile 路径 —— 防 PID 复用误杀用户浏览器。"""
        line = _command_line(pid)
        if not line:
            return False
        return str(self.profile).lower() in line.lower()

    def _terminate_own(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._port = None

    # ---- 轮询与记录 ----

    def _poll_loop(self) -> None:
        conn = None
        try:
            conn = store.connect()
            while not self._stop.wait(POLL_SECONDS):
                if (self._proc is not None and self._proc.poll() is not None
                        and not cdp.version_ok(self._port)):
                    self._message = "浏览器已退出"
                    break
                try:
                    pages = cdp.list_pages(self._port)
                except cdp.CdpError:
                    continue
                self._tabs = {page["id"]: {"url": page["url"], "title": page["title"]}
                              for page in pages}
                live = set(self._tabs)
                self._seen = {key: value for key, value in self._seen.items()
                              if key in live}
                self._record_pages(conn, pages)
        except Exception:
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _record_pages(self, conn, pages) -> None:
        settings = config.browser_settings()
        for page in pages:
            tab_id = str(page.get("id") or "")
            url = str(page.get("url") or "")
            title = str(page.get("title") or "")
            if not tab_id:
                continue
            previous = self._seen.get(tab_id)
            self._seen[tab_id] = (url, title)      # 暂停时也记，避免恢复后补记旧页面
            if not settings["record"]:
                continue
            if previous == (url, title):
                continue
            if not url.lower().startswith(("http://", "https://")):
                continue
            domain = urls.domain_of(url)
            if not domain or urls.is_loopback(domain):
                continue
            if urls.is_excluded(domain, settings["exclude_domains"]):
                continue
            try:
                store.add_browser_event(conn, tab_id=tab_id, url=url,
                                        title=title, domain=domain)
            except Exception:
                continue

    # ---- 查询 ----

    def history(self, *, limit: int = 20, days: int = 7,
                domain: str = "") -> list[dict]:
        conn = store.connect()
        try:
            return store.list_browser_events(conn, limit=limit, days=days, domain=domain)
        finally:
            conn.close()

    def clear_history(self) -> int:
        conn = store.connect()
        try:
            return store.clear_browser_events(conn)
        finally:
            conn.close()

    def set_recording(self, enabled: bool) -> dict:
        config.update_browser_settings(record=bool(enabled))
        return self.status()


_MANAGER: BrowserManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager() -> BrowserManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = BrowserManager()
        return _MANAGER
