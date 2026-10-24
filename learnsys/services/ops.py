"""「电脑助手」：AI 出操作计划 → 横栏预览 → 确认后执行。

安全三原则：
① AI 只能从**白名单操作目录**里挑，参数不齐/操作不认识的一律拒收；
② 动系统目录（Windows / Program Files）的操作直接拒绝；
③ 删除走**回收站**（可反悔），每一步执行结果都写日志。

纯函数 + 少量 ctypes，**不带 Qt**（确认弹窗归界面层）。
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import time

# ---- 操作目录（AI 只能挑这些；名字和参数都别改，改了老计划会失效）----

OPS: dict[str, dict] = {
    "open":       {"params": ["path"],              "desc": "用默认程序打开文件/文件夹/网址"},
    "launch_app": {"params": ["name"],              "desc": "按名字启动已安装的程序（开始菜单里搜得到的）"},
    "list_dir":   {"params": ["path"],              "desc": "列出文件夹内容"},
    "find_files": {"params": ["root", "pattern"],   "desc": "按通配符在文件夹里找文件（如 *.pdf）"},
    "dir_stats":  {"params": ["path", "top"],       "desc": "统计直接子项的占用大小，从大到小"},
    "mkdir":      {"params": ["path"],              "desc": "新建文件夹"},
    "move":       {"params": ["src", "dst_dir"],    "desc": "把文件/文件夹移进目标文件夹"},
    "copy":       {"params": ["src", "dst_dir"],    "desc": "复制到目标文件夹"},
    "rename":     {"params": ["path", "new_name"],  "desc": "重命名（只改名字，不换目录）"},
    "delete":     {"params": ["path"],              "desc": "删除到回收站（可反悔）"},
    "remind":     {"params": ["minutes", "message"], "desc": "几分钟后提醒一句话"},
}

# 动这些地方的操作一律拒绝（读目录里的文件不在此限，但删除/移动目标在下面就拒）
PROTECTED = ("c:/windows", "c:/program files", "c:/program files (x86)", "c:/programdata")

# 能直接执行的可执行文件 / 脚本一律不让「打开」——双击就是运行，确认框救不了。
OPEN_BLOCKED_SUFFIXES = {
    ".exe", ".bat", ".cmd", ".ps1", ".msi", ".lnk", ".url", ".scr", ".com",
    ".vbs", ".js", ".jse", ".wsf", ".hta", ".cpl", ".reg",
}
OPEN_MAX_PATH = 4096
APP_NAME_MAX = 60

# 常用根目录提示（拼进计划题里，AI 知道这台机器的盘面布局）
ROOT_HINT = "这台机器常用的位置：D:/学习系统（本程序数据）、D:/课件（课件）、C:/Users/<用户名>/Downloads（下载）"

# 电脑助手走 Agent 时用的系统提示：**不要**套导师口径，只要 JSON 计划。
SYSTEM_PROMPT = (
    "你是电脑操作助手。严格按用户消息里的要求输出 JSON 数组；"
    "只输出 JSON，不要解释、不要 Markdown 代码块以外的文字、不要加「想一想」。"
)


# ---- 计划的生成与解析 ----

def plan_question(user_request: str, today: str = "") -> str:
    """把用户的自然语言请求拼成「出操作计划」的题。today 传 'YYYY-MM-DD'。"""
    catalog = "\n".join(f"- {name}({', '.join(spec['params'])}) —— {spec['desc']}"
                        for name, spec in OPS.items())
    return (
        "你是电脑操作助手。根据下面的请求，输出一个操作计划。\n"
        f"可用操作（只能用这些）：\n{catalog}\n"
        f"今天是 {today or datetime.date.today().isoformat()}。{ROOT_HINT}。\n"
        "硬性要求：\n"
        "1. 先输出一个 JSON 数组，每项形如 {\"op\": \"操作名\", \"参数名\": \"值\", ...}，"
        "按执行顺序排；只输出 JSON，不要解释，不要 Markdown 代码块以外的话；\n"
        "2. 拿不准的路径就先用 list_dir / find_files 查，别编；\n"
        "3. 删除操作只能 delete（会进回收站）；\n"
        "4. 请求里带「提醒/过会儿叫我」就用 remind(分钟数, 要提醒的话)。\n"
        f"\n请求：{user_request}"
    )


def parse_plan(text: str) -> list[dict]:
    """从 AI 回复里抠出计划 JSON（容忍 ```json 围栏 / 前后废话）；抠不出返回空表。"""
    text = text.strip()
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        plan = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(plan, list):
        return []
    return [step for step in plan if isinstance(step, dict)]


def validate(step: dict) -> tuple[bool, str]:
    """单步校验：操作在目录里、参数齐全、写操作不碰系统目录。"""
    op = str(step.get("op") or "")
    spec = OPS.get(op)
    if spec is None:
        return False, f"不认识的操作：{op or '（空）'}"
    for param in spec["params"]:
        if step.get(param) in (None, ""):
            return False, f"{op} 缺参数 {param}"
    if op in ("move", "copy", "rename", "delete", "mkdir", "open"):
        for key in ("path", "src", "dst_dir"):
            if step.get(key) and is_protected(str(step[key])):
                return False, f"拒绝操作系统目录：{step[key]}"
    if op == "rename":
        if str(step.get("new_name", "")).strip() in ("", ".", ".."):
            return False, "新名字不合法"
    return True, ""


def is_protected(path: str) -> bool:
    norm = str(path).replace("\\", "/").lower().rstrip("/")
    return any(norm.startswith(prefix) for prefix in PROTECTED)


# ---- 执行 ----

_START_APPS_CACHE: tuple[float, dict[str, str]] = (0.0, {})
_START_APPS_TTL = 600.0


def parse_start_apps(text: str) -> dict[str, str]:
    """`Get-StartApps` 的 `名称|AppID` 输出 → 索引；坏行跳过。"""
    index: dict[str, str] = {}
    for line in str(text or "").splitlines():
        if "|" not in line:
            continue
        name, _, app_id = line.partition("|")
        name = name.strip()
        app_id = app_id.strip()
        if not name or not app_id:
            continue
        index.setdefault(name.lower(), f"shell:AppsFolder\\{app_id}")
    return index


def store_apps() -> dict[str, str]:
    """开始菜单里的 Microsoft Store / UWP 应用（记事本、计算器这类没有 .lnk）。

    `Get-StartApps` 是只读枚举，不带参数执行；失败就返回空表，不影响 .lnk 那套。
    """
    global _START_APPS_CACHE
    now = time.monotonic()
    if _START_APPS_CACHE[1] and now - _START_APPS_CACHE[0] < _START_APPS_TTL:
        return dict(_START_APPS_CACHE[1])
    if os.name != "nt":
        return {}
    command = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-StartApps | ForEach-Object { $_.Name + '|' + $_.AppID }")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, creationflags=0x08000000)
    except (OSError, subprocess.SubprocessError):
        return {}
    index = parse_start_apps(result.stdout)
    if index:
        _START_APPS_CACHE = (now, index)
    return dict(index)


def start_menu_apps(extra_dirs: list[pathlib.Path] | None = None) -> dict[str, str]:
    """开始菜单索引：小写程序名 → 启动目标（.lnk 路径或 `shell:AppsFolder\\<AppID>`）。"""
    roots = list(extra_dirs or [])
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(pathlib.Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    roots.append(pathlib.Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"))
    index: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for lnk in root.rglob("*.lnk"):
            name = lnk.stem.strip().lower()
            if name and name not in index:
                index[name] = str(lnk)
    for name, target in store_apps().items():    # .lnk 优先，同名不覆盖
        index.setdefault(name, target)
    return index


def find_app_name(name: str, index: dict[str, str]) -> str | None:
    """精确命中优先，其次包含匹配（"记事" → 记事本）；返回索引里的名字。"""
    name = str(name or "").strip().lower()
    if not name:
        return None
    if name in index:
        return name
    for key in index:
        if name in key:
            return key
    return None


def find_app(name: str, index: dict[str, str]) -> str | None:
    key = find_app_name(name, index)
    return index[key] if key is not None else None


def _is_http_url(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _is_unc(text: str) -> bool:
    """Windows 网络共享路径（`\\\\server\\share` 或 `//server/share`）。"""
    return text.startswith("\\\\") or text.startswith("//")


def open_path(path: str, *, allow_url: bool = False) -> str:
    """用默认程序打开文件 / 文件夹；返回一句中文结果，拒绝时抛 ValueError。

    这是「电脑助手 open」和「Agent open_file」唯一共用的实现 ——
    校验规则只在这里写一次。`allow_url=True` 只给电脑助手用（http/https 走默认浏览器）；
    Agent 的 open_file 传默认值，网址由工作台浏览器（P20.2）负责。
    """
    raw = str(path or "").strip()
    if not raw:
        raise ValueError("路径是空的。")
    if len(raw) > OPEN_MAX_PATH:
        raise ValueError(f"路径太长（上限 {OPEN_MAX_PATH} 字符）。")
    if allow_url and _is_http_url(raw):
        os.startfile(raw)
        return f"已打开网址：{raw}"
    if _is_unc(raw):
        raise ValueError("不能打开网络共享路径（\\\\服务器\\共享）—— 会触发网络访问。")
    target = pathlib.Path(raw)
    if not target.is_absolute():
        raise ValueError("只接受绝对路径（例如 D:\\课件\\网络.pdf），相对路径不知道从哪儿算。")
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise ValueError(f"路径解析失败：{exc}") from exc
    if is_protected(str(resolved)):
        raise ValueError(f"拒绝打开系统目录：{resolved}")
    if resolved.suffix.lower() in OPEN_BLOCKED_SUFFIXES:
        raise ValueError(
            f"不允许打开可执行文件或脚本（{resolved.suffix}）：双击等于运行，风险太高。")
    if not resolved.exists():
        raise ValueError(f"找不到这个文件或文件夹：{raw}")
    os.startfile(str(resolved))
    kind = "文件夹" if resolved.is_dir() else "文件"
    return f"已打开{kind}：{resolved}"


def launch_by_name(name: str, index: dict[str, str] | None = None) -> str:
    """按开始菜单里的名字启动程序；找不到就报中文原因并给候选，不猜、不执行。"""
    text = " ".join(str(name or "").split())
    if not text:
        raise ValueError("程序名是空的。")
    if len(text) > APP_NAME_MAX:
        raise ValueError(f"程序名太长（上限 {APP_NAME_MAX} 个字符）。")
    apps = index if index is not None else start_menu_apps()
    matched = find_app_name(text, apps)
    if matched is None:
        import difflib
        candidates = difflib.get_close_matches(
            text.lower(), sorted(apps), n=10, cutoff=0.3
        ) or sorted(apps)[:10]
        hint = ("候选：" + "、".join(candidates)
                if candidates else "开始菜单里没有任何可启动的程序。")
        raise ValueError(f"开始菜单里没找到「{text}」—— {hint}")
    target = apps[matched]
    os.startfile(target)
    return f"已启动程序：{matched}"


def recycle(path: str) -> None:
    """删到回收站（SHFileOperationW 带 FOF_ALLOWUNDO），比直接 unlink 可反悔。"""
    import ctypes
    from ctypes import wintypes
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint),
                    ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = 3                              # FO_DELETE
    op.pFrom = str(path) + "\x00"             # 双零结尾
    op.pTo = None
    op.fFlags = 0x0040 | 0x0010 | 0x0004      # ALLOWUNDO | NOCONFIRMATION | NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise OSError(f"删除到回收站失败（代码 {result}）")


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def describe(step: dict) -> str:
    """一步计划 → 给人预览的一句话（执行前看的就是它）。"""
    op = step.get("op")
    arg = lambda k: str(step.get(k, ""))     # noqa: E731
    table = {
        "open": f"打开 {arg('path')}",
        "launch_app": f"启动程序「{arg('name')}」",
        "list_dir": f"查看 {arg('path')} 里有什么",
        "find_files": f"在 {arg('root')} 里找 {arg('pattern')}",
        "dir_stats": f"统计 {arg('path')} 下各项占用（前 {arg('top') or 5}）",
        "mkdir": f"新建文件夹 {arg('path')}",
        "move": f"移动 {arg('src')} → {arg('dst_dir')}",
        "copy": f"复制 {arg('src')} → {arg('dst_dir')}",
        "rename": f"重命名 {arg('path')} 为 {arg('new_name')}",
        "delete": f"删除到回收站：{arg('path')}",
        "remind": f"{arg('minutes')} 分钟后提醒：{arg('message')}",
    }
    return table.get(op, f"{op} {step}")


def execute(step: dict, app_index: dict[str, str] | None = None) -> str:
    """执行单步，返回给人看的结果一句话；出错抛 OSError/ValueError。"""
    op = step.get("op")
    ok, err = validate(step)
    if not ok:
        raise ValueError(err)
    if op == "open":
        # 电脑助手保留「打开网址」能力（走默认浏览器）；文件/文件夹走同一套校验。
        return open_path(str(step["path"]), allow_url=True)
    if op == "launch_app":
        return launch_by_name(str(step["name"]), app_index)
    if op == "list_dir":
        target = pathlib.Path(str(step["path"]))
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        lines = [f"{'[目录]' if p.is_dir() else '[文件]'} {p.name}" for p in entries[:50]]
        return f"{target} 共 {len(entries)} 项：\n" + "\n".join(lines[:50])
    if op == "find_files":
        root, pattern = pathlib.Path(str(step["root"])), str(step["pattern"])
        hits = [str(p) for p in root.rglob(pattern)][:100]
        return f"找到 {len(hits)} 个：\n" + "\n".join(hits[:50])
    if op == "dir_stats":
        target = pathlib.Path(str(step["path"]))
        top = int(step.get("top") or 5)
        sizes = []
        for child in target.iterdir():
            total = 0
            if child.is_file():
                total = child.stat().st_size
            elif child.is_dir():
                for f in child.rglob("*"):
                    try:
                        if f.is_file():
                            total += f.stat().st_size
                    except OSError:
                        pass
            sizes.append((child.name, total))
        sizes.sort(key=lambda kv: kv[1], reverse=True)
        return f"{target} 各项占用：\n" + "\n".join(
            f"{name}  {human_size(size)}" for name, size in sizes[:top])
    if op == "mkdir":
        target = pathlib.Path(str(step["path"]))
        target.mkdir(parents=True, exist_ok=True)
        return f"文件夹就绪：{target}"
    if op == "move":
        src, dst_dir = pathlib.Path(str(step["src"])), pathlib.Path(str(step["dst_dir"]))
        if not src.exists():
            raise FileNotFoundError(f"找不到 {src}")
        dst_dir.mkdir(parents=True, exist_ok=True)
        moved = dst_dir / src.name
        shutil.move(str(src), str(moved))
        return f"已移动 {src.name} → {moved}"
    if op == "copy":
        src, dst_dir = pathlib.Path(str(step["src"])), pathlib.Path(str(step["dst_dir"]))
        if not src.exists():
            raise FileNotFoundError(f"找不到 {src}")
        dst_dir.mkdir(parents=True, exist_ok=True)
        copied = dst_dir / src.name
        if src.is_dir():
            shutil.copytree(src, copied)
        else:
            shutil.copy2(src, copied)
        return f"已复制 {src.name} → {copied}"
    if op == "rename":
        path = pathlib.Path(str(step["path"]))
        new = path.with_name(str(step["new_name"]))
        path.rename(new)
        return f"已重命名为 {new.name}"
    if op == "delete":
        target = str(step["path"])
        recycle(target)
        return f"已删除到回收站：{target}"
    if op == "remind":
        return f"已设提醒：{step.get('minutes')} 分钟后 —— {step.get('message')}"
    raise ValueError(f"不认识的操作：{op}")
