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

# 常用根目录提示（拼进计划题里，AI 知道这台机器的盘面布局）
ROOT_HINT = "这台机器常用的位置：D:/学习系统（本程序数据）、D:/课件（课件）、C:/Users/<用户名>/Downloads（下载）"


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

def start_menu_apps(extra_dirs: list[pathlib.Path] | None = None) -> dict[str, str]:
    """开始菜单里的快捷方式索引：小写程序名 → .lnk 路径（launch_app 用）。"""
    import os
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
    return index


def find_app(name: str, index: dict[str, str]) -> str | None:
    name = name.strip().lower()
    if not name:
        return None
    if name in index:
        return index[name]
    for key, path in index.items():          # 退一步：包含匹配（"记事" → 记事本）
        if name in key:
            return path
    return None


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
        target = str(step["path"])
        os.startfile(target)                              # 文件/文件夹/网址通吃
        return f"已打开 {target}"
    if op == "launch_app":
        name = str(step["name"])
        lnk = find_app(name, app_index or start_menu_apps())
        if lnk is None:
            raise ValueError(f"开始菜单里没找到「{name}」—— 试试程序的完整名字")
        os.startfile(lnk)
        return f"已启动 {lnk and pathlib.Path(lnk).stem}"
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
