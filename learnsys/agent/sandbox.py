"""代码运行沙箱：临时目录 + 超时 + 输出上限 + 进程限额 + 默认禁网。

**能力边界（必须说清）**：这是给「AI 生成的学习示例代码」用的**资源沙箱**，
不是对抗恶意代码的内核级隔离。Windows 用户态没有管理员权限时，无法真正切断
一个子进程的网络；这里做的是默认拒绝：

- 静态检查网络 API / URL，命中就不运行；
- 不提供任何密钥、代理环境变量；
- 进程放进 Job 对象：内存上限、活动进程数上限、超时后整棵进程树杀掉；
- 输出超过上限立即截断并终止；
- 工作目录是临时目录，结束后删除；不读写数据目录以外的路径。

真要做到内核级禁网，需要 AppContainer / 容器 / 防火墙规则（管理员权限），
留给后续阶段。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import dataclasses
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

MAX_CODE_BYTES = 100_000
DEFAULT_TIMEOUT = 10.0
DEFAULT_OUTPUT_LIMIT = 64 * 1024
DEFAULT_MEMORY_MB = 512
COMPILE_TIMEOUT = 20.0
COMPILE_OUTPUT_LIMIT = 20_000

LANGUAGES = {
    "cpp": {"label": "C++", "suffix": ".cpp"},
    "c": {"label": "C", "suffix": ".c"},
    "python": {"label": "Python", "suffix": ".py"},
}

NETWORK_PATTERNS = [
    (re.compile(r"\b(?:import|from)\s+(socket|ssl|http|urllib|urllib2|urllib3|"
                r"requests|httpx|aiohttp|ftplib|smtplib|telnetlib|xmlrpc|"
                r"websockets|paramiko|scapy)\b"), "Python 网络模块"),
    (re.compile(r"#\s*include\s*[<\"](winsock2|ws2tcpip|wininet|winhttp|curl|"
                r"boost/asio|asio)\b"), "网络头文件"),
    (re.compile(r"\b(WSAStartup|gethostbyname|getaddrinfo|socket|connect|"
                r"InternetOpen[A-Za-z]*|URLDownloadToFile[A-Za-z]*|"
                r"WinHttp[A-Za-z]*|curl_easy_init|curl_global_init)\b"),
     "网络 API"),
    (re.compile(r"https?://", re.IGNORECASE), "网址"),
    (re.compile(r"\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod)\b",
                re.IGNORECASE), "下载命令"),
]

IS_WINDOWS = os.name == "nt"
_CREATE_NO_WINDOW = 0x08000000


@dataclasses.dataclass
class SandboxResult:
    ok: bool
    language: str = ""
    command: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    duration_ms: int = 0
    note: str = ""

    def preview(self) -> str:
        label = LANGUAGES.get(self.language, {}).get("label", self.language)
        if self.timed_out:
            return f"{label} 运行超时"
        if not self.ok:
            if "编译失败" in self.note:
                return f"{label} 编译失败"
            if "禁网" in self.note:
                return "网络代码被拒绝"
            return f"{label} 运行失败"
        extra = "（输出已截断）" if self.truncated else ""
        return f"{label} 运行成功{extra}"

    def render(self) -> str:
        label = LANGUAGES.get(self.language, {}).get("label", self.language)
        lines = [f"【代码运行 · {label}】{self.note or ('运行成功' if self.ok else '运行失败')}",
                 f"耗时 {self.duration_ms} 毫秒；退出码 {self.exit_code}"]
        if self.command:
            lines.append("命令：" + self.command)
        if self.stdout:
            lines += ["", "标准输出：", self.stdout]
        if self.stderr:
            lines += ["", "错误输出：", self.stderr]
        if self.truncated:
            lines += ["", "（输出超过上限，已截断并终止进程）"]
        return "\n".join(lines)


def normalize_language(language: str) -> str:
    value = str(language or "").strip().lower()
    aliases = {"c++": "cpp", "cxx": "cpp", "py": "python", "python3": "python"}
    return aliases.get(value, value)


def guess_language(code: str) -> str:
    """模型偶尔漏传 / 传错 language；按代码特征补一个，别让一次运行白等。

    只在「没给或给了不认识的值」时用；识别不出就返回空串，由调用方报错。
    """
    text = str(code or "")
    if not text.strip():
        return ""
    lower = text.lower()
    if ("def " in text and ":" in text) or "import " in lower or (
            "print(" in lower and ";" not in text and "#include" not in lower):
        return "python"
    if "#include" in lower:
        if any(word in lower for word in ("iostream", "using namespace std", "std::",
                                          "cout", "cin", "template<", "template <")):
            return "cpp"
        if any(word in lower for word in ("stdio.h", "stdlib.h", "string.h", "printf(",
                                          "scanf(", "struct ")):
            return "c"
        return "cpp"          # 只有 #include 时按 C++ 试，编译器会给出真实错误
    if any(word in lower for word in ("cout", "cin", "std::", "using namespace std")):
        return "cpp"
    return ""


def runtime_available(language: str) -> bool:
    language = normalize_language(language)
    if language == "python":
        return bool(sys.executable)
    if language == "cpp":
        return bool(shutil.which("g++"))
    if language == "c":
        return bool(shutil.which("gcc"))
    return False


def network_findings(code: str) -> list[str]:
    """静态禁网检查；返回命中的类别（空 = 通过）。"""
    text = str(code or "")
    found: list[str] = []
    for pattern, label in NETWORK_PATTERNS:
        if pattern.search(text) and label not in found:
            found.append(label)
    return found


def _decode(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "gbk", "mbcs"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _clean_env(workdir: pathlib.Path, extra_path: str = "") -> dict:
    """只给最小环境：没有密钥、没有代理、没有用户 PATH。

    `extra_path` 只给编译器用：g++ 要靠 PATH 找到自己的 cc1plus / as / ld。
    被运行的代码永远拿不到它。
    """
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    path = str(pathlib.Path(system_root) / "System32") + ";" + system_root
    if extra_path:
        path = extra_path + ";" + path
    return {
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "COMSPEC": str(pathlib.Path(system_root) / "System32" / "cmd.exe"),
        "PATH": path,
        "TEMP": str(workdir),
        "TMP": str(workdir),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_PROXY": "*",
    }


# ---- Windows Job 对象：内存 / 活动进程数 / 一关句柄就杀光 ----

class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", w.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", w.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", w.DWORD),
        ("SchedulingClass", w.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9


def _make_job(memory_mb: int):
    if not IS_WINDOWS:
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_JOB_MEMORY
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
    info.BasicLimitInformation.ActiveProcessLimit = 8
    info.ProcessMemoryLimit = int(memory_mb) * 1024 * 1024
    info.JobMemoryLimit = int(memory_mb) * 1024 * 1024
    ok = kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(info),
        ctypes.sizeof(info))
    if not ok:
        kernel32.CloseHandle(job)
        return None
    return job


def _assign_job(job, proc) -> None:
    if not job or not IS_WINDOWS:
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject(job, w.HANDLE(int(proc._handle)))
    except Exception:
        pass


def _kill_job(job, proc) -> None:
    if job and IS_WINDOWS:
        try:
            ctypes.WinDLL("kernel32", use_last_error=True).TerminateJobObject(job, 1)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


def _close_job(job) -> None:
    if job and IS_WINDOWS:
        try:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)
        except Exception:
            pass


def _run_process(argv: list[str], *, cwd: pathlib.Path, timeout: float,
                 output_limit: int, memory_mb: int,
                 stdin_text: str = "", extra_path: str = "") -> dict:
    """跑一个进程；超时/输出超限时杀整棵进程树。"""
    job = _make_job(memory_mb)
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), env=_clean_env(cwd, extra_path=extra_path),
            stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=_CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )
    except OSError as exc:
        _close_job(job)
        return {"stdout": "", "stderr": f"启动失败：{exc}", "exit_code": None,
                "timed_out": False, "truncated": False,
                "duration_ms": int((time.monotonic() - started) * 1000)}
    _assign_job(job, proc)

    lock = threading.Lock()
    chunks = {"out": bytearray(), "err": bytearray()}
    state = {"bytes": 0, "truncated": False}

    def reader(stream, key: str):
        while True:
            piece = stream.read(4096)
            if not piece:
                break
            with lock:
                remaining = output_limit - state["bytes"]
                if remaining > 0:
                    chunks[key] += piece[:remaining]
                    state["bytes"] += min(len(piece), remaining)
                if len(piece) > remaining:
                    state["truncated"] = True
            if state["truncated"]:
                _kill_job(job, proc)
                break

    def feed():
        try:
            proc.stdin.write(stdin_text.encode("utf-8", errors="replace"))
            proc.stdin.close()
        except Exception:
            pass

    threads = [threading.Thread(target=reader, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=reader, args=(proc.stderr, "err"), daemon=True)]
    for thread in threads:
        thread.start()
    if stdin_text:
        threading.Thread(target=feed, daemon=True).start()

    timed_out = False
    try:
        proc.wait(timeout=max(0.5, float(timeout)))
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_job(job, proc)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
    for thread in threads:
        thread.join(timeout=2)
    try:
        proc.stdout.close()
        proc.stderr.close()
    except Exception:
        pass
    _close_job(job)
    return {
        "stdout": _decode(bytes(chunks["out"])),
        "stderr": _decode(bytes(chunks["err"])),
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "truncated": bool(state["truncated"]),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def run(language: str, code: str, *, stdin_text: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        output_limit: int = DEFAULT_OUTPUT_LIMIT,
        memory_mb: int = DEFAULT_MEMORY_MB) -> SandboxResult:
    """在临时目录里编译/运行一段代码；任何失败都给中文原因。"""
    code = str(code or "")
    language = normalize_language(language)
    if language not in LANGUAGES:
        language = guess_language(code)          # 漏传 / 传错：按代码特征补
    if language not in LANGUAGES:
        return SandboxResult(False, language=language,
                             note=f"不支持的语言「{language}」，只支持 C++ / C / Python。")
    if not code.strip():
        return SandboxResult(False, language=language, note="代码是空的。")
    if len(code.encode("utf-8", errors="replace")) > MAX_CODE_BYTES:
        return SandboxResult(False, language=language,
                             note=f"代码太长（上限 {MAX_CODE_BYTES // 1000} KB）。")
    findings = network_findings(code)
    if findings:
        return SandboxResult(
            False, language=language,
            note="默认禁网：代码里出现了" + "、".join(findings) + "，已拒绝运行。"
                 "沙箱不提供网络，也不带任何密钥；需要联网的例子请先说明用途，"
                 "由用户决定是否在沙箱外运行。")
    if not runtime_available(language):
        tool = "g++" if language == "cpp" else ("gcc" if language == "c" else "Python")
        return SandboxResult(False, language=language,
                             note=f"本机没有找到 {tool}，无法运行这段代码。")

    workdir = pathlib.Path(tempfile.mkdtemp(prefix="learnsys-run-"))
    source = workdir / ("main" + LANGUAGES[language]["suffix"])
    source.write_text(code, encoding="utf-8")
    started = time.monotonic()
    try:
        if language in ("cpp", "c"):
            compiler = shutil.which("g++" if language == "cpp" else "gcc")
            exe = workdir / "main.exe"
            argv = [compiler, "-O0"]
            if language == "cpp":
                argv.append("-std=c++17")
            argv += ["-static", str(source), "-o", str(exe)]
            compiled = _run_process(argv, cwd=workdir,
                                    timeout=COMPILE_TIMEOUT,
                                    output_limit=COMPILE_OUTPUT_LIMIT,
                                    memory_mb=max(1024, memory_mb),
                                    extra_path=str(pathlib.Path(compiler).parent))
            if compiled["timed_out"]:
                return SandboxResult(False, language=language,
                                     command=" ".join(argv),
                                     stdout=compiled["stdout"],
                                     stderr=compiled["stderr"],
                                     timed_out=True,
                                     duration_ms=int((time.monotonic() - started) * 1000),
                                     note="编译超时（超过 20 秒）。")
            if compiled["exit_code"] != 0 or not exe.exists():
                return SandboxResult(
                    False, language=language, command=" ".join(argv),
                    stdout=compiled["stdout"], stderr=compiled["stderr"],
                    exit_code=compiled["exit_code"],
                    duration_ms=int((time.monotonic() - started) * 1000),
                    note=f"编译失败（编译器退出码 {compiled['exit_code']}）。")
            command = str(exe)
            argv = [str(exe)]
        else:
            command = sys.executable
            # `-I` 会忽略 PYTHONIOENCODING / PYTHONUTF8（隔离模式连环境变量也不看），
            # 英文 Windows（cp1252）下 print('你好') 会直接 UnicodeEncodeError。
            # 用命令行 `-X utf8` 强制 UTF-8 模式，和 -I 的隔离不冲突。
            argv = [sys.executable, "-I", "-B", "-X", "utf8", str(source)]

        result = _run_process(argv, cwd=workdir, timeout=timeout,
                              output_limit=output_limit, memory_mb=memory_mb,
                              stdin_text=str(stdin_text or ""))
        elapsed = int((time.monotonic() - started) * 1000)
        if result["timed_out"]:
            note = f"运行超时（超过 {timeout:g} 秒），进程已被终止。"
            ok = False
        elif result["truncated"]:
            note = "输出超过上限，已截断并终止进程。"
            ok = False
        elif result["exit_code"] != 0:
            note = f"运行失败（退出码 {result['exit_code']}）。"
            ok = False
        else:
            note = "运行成功。"
            ok = True
        return SandboxResult(
            ok, language=language, command=command,
            stdout=result["stdout"], stderr=result["stderr"],
            exit_code=result["exit_code"], timed_out=result["timed_out"],
            truncated=result["truncated"], duration_ms=elapsed, note=note)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
