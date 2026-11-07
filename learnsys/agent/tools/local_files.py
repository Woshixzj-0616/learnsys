"""本机文件：白名单目录的只读检索与分段读取。

P34.2 起检索走 `services/local_index` 的后台索引（SQL），本模块只负责
读取、分段与结果排版；白名单与敏感文件的判断也归 `local_index`，不在这里维护第二份。

- 只读，不改文件、不移动；写仍只落「学习档案」。
- 敏感文件（密钥 / 数据库 / 浏览器登录数据）永远不读，哪怕在目录里。
- 正文按扩展名抽取，分段返回，不把整份塞给模型。
"""
from __future__ import annotations

import codecs
import datetime
import json
import pathlib
import threading

from learnsys.services import local_index
from learnsys.services.local_index import (EXCLUDE_DIRS, SENSITIVE_NAMES,
                                           SENSITIVE_SUFFIXES, is_allowed_path,
                                           resolve_path, roots)
from learnsys.services.study.document import extract_document

__all__ = ["EXCLUDE_DIRS", "SENSITIVE_NAMES", "SENSITIVE_SUFFIXES",
           "is_allowed_path", "resolve_path", "roots", "read_local_file",
           "search_local_files"]

DOC_SUFFIXES = {".pdf", ".docx", ".pptx"}
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
TEXT_CACHE_MAX = 6

_LOCK = threading.Lock()
_TEXT_CACHE: dict[tuple[str, int, int], tuple[str, str]] = {}


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
    """在白名单目录的索引里按文件名 / 路径找文件；不读正文。"""
    try:
        result = local_index.search(query, limit, suffix)
    except Exception as exc:  # noqa: BLE001 —— 工具错误转成中文文本，不裸抛给模型
        return f"搜本机文件失败：{exc}"

    roots_now = result["roots"]
    if not roots_now:
        return ("还没设置「本机可读目录」。告诉用户：在 工具 → 本机可读目录 里"
                "添加要允许读取的文件夹（例如 D:\\学习资料），保存后就能直接读，不用导入。")

    entries = result["entries"]
    total = int(result.get("total") or 0)
    matched = int(result.get("matched") or 0)
    if not entries:
        where = "、".join(roots_now)
        what = f"「{query}」" if query else (suffix or "文件")
        return f"在可读目录里没找到{what}。可读目录：{where}"

    lines = [f"在本机可读目录里找到 {len(entries)} 个文件"
             f"（索引共 {total} 个；只列元数据，正文用 read_local_file 读）："]
    for path, _name_l, size, mtime_ns in entries:
        lines.append(f"- {path} · {_size_text(size)} · "
                     f"{_mtime_text(int(mtime_ns) / 1_000_000_000)}")
    if matched > len(entries):
        lines.append(f"（还有 {matched - len(entries)} 个；加关键词或 suffix 缩小范围。）")
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


def _text_of(path, stat) -> tuple[str, str]:
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


def _audit(ctx, path, chars: int) -> None:
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
    root = local_index._matching_root(target)
    if local_index._sensitive(target, root):
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
    except Exception as exc:  # noqa: BLE001 —— 文档抽取失败也按可读文本报错
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
