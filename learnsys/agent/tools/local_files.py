"""本机文件：白名单目录的只读检索与分段读取。

P34.1 口径：
- 只读，不改文件、不移动；写仍只落「学习档案」。
- 只认设置里 `materials.import_dirs` 的目录（和资料批量导入共用同一份清单）。
- 敏感文件（密钥 / 数据库 / 浏览器登录数据）永远不读，哪怕在目录里。
- 检索只走文件名 / 路径；正文按扩展名抽取，分段返回，不把整份塞给模型。
"""
from __future__ import annotations

import codecs
import datetime
import json
import os
import pathlib
import threading
import time

from learnsys import config
from learnsys.services.study.document import extract_document

EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".ssh", ".gnupg", "node_modules", ".venv", "venv",
    "__pycache__", "appdata", "$recycle.bin", "system volume information",
    ".cache", ".npm", ".gradle", ".mypy_cache", ".pytest_cache",
}
SENSITIVE_NAMES = {
    "设置.json", "界面设置.json", ".env", "id_rsa", "id_dsa", "id_ecdsa",
    "id_ed25519", "credentials", "credentials.json", "login data", "cookies",
    "cookies.sqlite", "ntuser.dat", "sam", "system",
}
SENSITIVE_SUFFIXES = {
    ".pem", ".key", ".pfx", ".p12", ".kdbx", ".jks", ".keystore",
    ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3",
}
DOC_SUFFIXES = {".pdf", ".docx", ".pptx"}
MAX_ENTRIES = 40_000
MAX_DEPTH = 12
SCAN_SECONDS = 3.0
CACHE_TTL = 60.0
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
TEXT_CACHE_MAX = 6

_LOCK = threading.Lock()
_SCAN_CACHE: dict[str, tuple[float, list[tuple]]] = {}
_TEXT_CACHE: dict[tuple[str, int, int], tuple[str, str]] = {}


def roots() -> list[pathlib.Path]:
    """设置里的本机可读目录；不存在或非目录的条目自动跳过。"""
    section = config.USER.get("materials")
    raw = section.get("import_dirs") if isinstance(section, dict) else []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[pathlib.Path] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            path = pathlib.Path(text).expanduser().resolve()
        except (OSError, ValueError):
            continue
        if not path.is_dir():
            continue
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def resolve_path(raw) -> pathlib.Path | None:
    """绝对路径原样解析；相对路径依次尝试各白名单目录。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        path = pathlib.Path(text).expanduser()
    except (OSError, ValueError):
        return None
    if ":" in path.name:          # Windows 备用数据流：file.txt:secret 不算普通文件
        return None
    try:
        if path.is_absolute():
            return path.resolve()
    except OSError:
        return None
    for root in roots():
        candidate = (root / path)
        try:
            if candidate.exists():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _matching_root(path: pathlib.Path) -> pathlib.Path | None:
    for root in roots():
        if _within(path, root):
            return root
    return None


def _sensitive(path: pathlib.Path, root: pathlib.Path | None = None) -> bool:
    """密钥 / 数据库 / 浏览器登录数据：检索与读取都跳过。

    目录名看「相对白名单根」的部分：白名单本身在 AppData 下（测试临时目录）不算敏感，
    只有根里的 AppData 子目录才跳过。
    """
    # Windows 会忽略文件名末尾的点和空格：`设置.json ` 仍是同一个文件。
    name = path.name.casefold().rstrip(" .")
    if name in SENSITIVE_NAMES or name.startswith(".env"):
        return True
    if pathlib.PurePath(name).suffix in SENSITIVE_SUFFIXES:
        return True
    if root is not None:
        rel = path.relative_to(root)
        return any(part.casefold() in EXCLUDE_DIRS for part in rel.parts[:-1])
    # 白名单外：只拦密钥目录；APPData / node_modules 这类噪音目录靠确认框兜底。
    return bool({part.casefold() for part in path.parts} & {".ssh", ".gnupg"})


def is_allowed_path(raw) -> bool:
    """路径是否在白名单目录内且不是敏感文件。"""
    path = resolve_path(raw)
    if path is None:
        return False
    root = _matching_root(path)
    if root is None:
        return False
    return not _sensitive(path, root)


def _scan(root: pathlib.Path) -> list[tuple]:
    key = str(root)
    now = time.monotonic()
    with _LOCK:
        cached = _SCAN_CACHE.get(key)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]

    entries: list[tuple] = []
    deadline = now + SCAN_SECONDS
    stack: list[tuple[pathlib.Path, int]] = [(root, 0)]
    while stack and len(entries) < MAX_ENTRIES and time.monotonic() < deadline:
        folder, depth = stack.pop()
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            name = entry.name.casefold()
                            if (depth < MAX_DEPTH and name not in EXCLUDE_DIRS
                                    and not entry.name.startswith(".")):
                                stack.append((pathlib.Path(entry.path), depth + 1))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        path = pathlib.Path(entry.path)
                        if _sensitive(path, root):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        entries.append((str(path), entry.name.casefold(),
                                        path.suffix.casefold(), stat.st_size,
                                        stat.st_mtime))
                    except OSError:
                        continue
                    if len(entries) >= MAX_ENTRIES:
                        break
        except OSError:
            continue

    with _LOCK:
        _SCAN_CACHE[key] = (time.monotonic(), entries)
    return entries


def _size_text(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _mtime_text(stamp: float) -> str:
    try:
        return datetime.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d")
    except (OSError, ValueError, OverflowError):
        return ""


def search_local_files(query: str = "", limit: int = 10, suffix: str = "",
                       *, ctx=None) -> str:
    """在白名单目录里按文件名 / 路径找文件；不读正文。"""
    roots_now = roots()
    if not roots_now:
        return ("还没设置「本机可读目录」。告诉用户：在 工具 → 本机可读目录 里"
                "添加要允许读取的文件夹（例如 D:\\学习资料），保存后就能直接读，不用导入。")
    limit = max(1, min(int(limit or 10), 20))
    needle = str(suffix or "").strip().casefold()
    if needle and not needle.startswith("."):
        needle = "." + needle
    tokens = [part for part in str(query or "").casefold().split() if part]

    matched: list[tuple] = []
    total = 0
    for root in roots_now:
        for entry in _scan(root):
            total += 1
            path, name, ext, size, mtime = entry
            if needle and ext != needle:
                continue
            if tokens and not all(token in name or token in path.casefold()
                                  for token in tokens):
                continue
            score = 0
            if tokens and name == " ".join(tokens):
                score = 0
            elif tokens and all(token in name for token in tokens):
                score = 1 if name.startswith(tokens[0]) else 2
            elif tokens:
                score = 3
            matched.append((score, -mtime, path, size, mtime))

    if not matched:
        where = "、".join(str(root) for root in roots_now)
        what = f"「{query}」" if query else (suffix or "文件")
        return f"在可读目录里没找到{what}。可读目录：{where}"

    matched.sort()
    lines = [f"在本机可读目录里找到 {min(len(matched), limit)} 个文件"
             f"（共扫到 {total} 个；只列元数据，正文用 read_local_file 读）："]
    for _score, _neg, path, size, mtime in matched[:limit]:
        lines.append(f"- {path} · {_size_text(size)} · {_mtime_text(mtime)}")
    if len(matched) > limit:
        lines.append(f"（还有 {len(matched) - limit} 个；加关键词或 suffix 缩小范围。）")
    return "\n".join(lines)


def _decode(raw: bytes) -> str:
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gb18030")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _text_of(path: pathlib.Path, stat: os.stat_result) -> tuple[str, str]:
    key = (str(path), int(stat.st_mtime_ns), int(stat.st_size))
    with _LOCK:
        cached = _TEXT_CACHE.get(key)
    if cached is not None:
        return cached

    if path.suffix.casefold() in DOC_SUFFIXES:
        data = extract_document(str(path))
        text, kind = str(data.get("text") or ""), str(data.get("kind") or "doc")
    else:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("文件太大（上限 25 MB），没有读取")
        if b"\x00" in raw[:4096]:
            raise ValueError("这是二进制文件，没有读取")
        text = _decode(raw)
        kind = path.suffix.lstrip(".").casefold() or "text"

    text = text[:MAX_TEXT_CHARS]
    with _LOCK:
        if len(_TEXT_CACHE) >= TEXT_CACHE_MAX:
            _TEXT_CACHE.pop(next(iter(_TEXT_CACHE)))
        _TEXT_CACHE[key] = (text, kind)
    return text, kind


def _audit(ctx, path: pathlib.Path, chars: int) -> None:
    """读取留痕：路径、字数、时间、会话；写失败不影响读取。"""
    try:
        folder = pathlib.Path(ctx.data_root) / "日志"
        folder.mkdir(parents=True, exist_ok=True)
        line = json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "conversation_id": getattr(ctx, "conversation_id", None),
            "path": str(path),
            "chars": int(chars),
        }, ensure_ascii=False)
        with open(folder / "本机文件读取.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def read_local_file(path: str, offset: int = 0, length: int = 6000, *,
                    ctx) -> str:
    """分段读一个本机文件；白名单外需在确认框里允许。"""
    target = resolve_path(path)
    if target is None:
        return f"没有找到这个文件：{path}"
    root = _matching_root(target)
    if _sensitive(target, root):
        return "这个文件属于密钥 / 数据库 / 浏览器登录数据，按安全规则不读。"
    approved = {str(item).casefold() for item in getattr(ctx, "approved_paths", ())}
    if root is None and str(target).casefold() not in approved:
        return ("这个路径不在「本机可读目录」里，没有读取。"
                "如果确实要读，请在确认框里允许；或让用户在 工具 → 本机可读目录 里加上它。")
    if not target.is_file():
        return f"这不是一个文件：{target}"

    try:
        stat = target.stat()
    except OSError as exc:
        return f"读文件失败：{exc}"
    if stat.st_size > MAX_FILE_BYTES:
        return "文件太大（上限 25 MB），没有读取。"
    try:
        text, kind = _text_of(target, stat)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return f"读文件失败：{exc}"

    try:
        start = max(0, int(offset or 0))
    except (TypeError, ValueError):
        start = 0
    try:
        size = max(500, min(int(length or 6000), 12000))
    except (TypeError, ValueError):
        size = 6000
    piece = text[start:start + size]
    if not piece:
        return f"文件已经读完了（共 {len(text)} 字）。"

    page_info = ""
    if "\f" in text:
        start_page = text[:start].count("\f") + 1
        end_page = text[:start + len(piece)].count("\f") + 1
        page_info = (f"第 {start_page} 页" if start_page == end_page
                     else f"第 {start_page}–{end_page} 页") + "；"
    head = (f"【本机文件：{target.name} · {kind} · 共 {len(text)} 字；{page_info}"
            f"本次读 {start}–{start + len(piece)} 字】")
    tail = "" if start + len(piece) >= len(text) else (
        f"\n（后面还有 {len(text) - start - len(piece)} 字，offset="
        f"{start + len(piece)} 接着读）")
    _audit(ctx, target, len(piece))
    return head + "\n" + piece + tail
