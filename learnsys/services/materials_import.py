"""资料库批量导入：只读扫描白名单目录，按 SHA256 去重。

两条入口：
- 课程资料：设置里 `materials.import_dirs` 列出的目录，递归找 PDF/DOCX/PPTX/TXT/MD；
- Obsidian：`materials.obsidian_dir` 指定的库，只导入 `.md`，默认不自动扫。

原文件不移动、不改名；正文和原文副本进数据目录，和手动上传走同一条入库路径。
"""
from __future__ import annotations

import hashlib
import pathlib
import uuid

from learnsys import config as app_config
from learnsys import store
from learnsys.ask import study

SUFFIXES = {".pdf", ".docx", ".pptx", ".txt", ".md"}
MAX_FILES = 300
MAX_BYTES = 50 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_DEPTH = 8
SKIP_DIRS = {"node_modules", ".git", ".obsidian", "资料库", "回收站"}


def _settings() -> dict:
    raw = app_config.USER.get("materials")
    return raw if isinstance(raw, dict) else {}


def _as_roots(value) -> list[pathlib.Path]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    roots: list[pathlib.Path] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            root = pathlib.Path(text).expanduser().resolve()
        except (OSError, ValueError):
            continue
        if root.is_dir():
            roots.append(root)
    return roots


def allowed_roots() -> list[pathlib.Path]:
    return _as_roots(_settings().get("import_dirs"))


def obsidian_root() -> pathlib.Path | None:
    roots = _as_roots(_settings().get("obsidian_dir"))
    return roots[0] if roots else None


def _within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _iter_files(root: pathlib.Path, suffixes: set[str], recursive: bool):
    """稳定顺序遍历；跳过隐藏目录和大目录，最多 MAX_DEPTH 层。"""
    stack: list[tuple[pathlib.Path, int]] = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = sorted(folder.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if (recursive and depth < MAX_DEPTH
                            and entry.name not in SKIP_DIRS
                            and not entry.name.startswith(".")):
                        stack.append((entry, depth + 1))
                    continue
            except OSError:
                continue
            if entry.suffix.lower() in suffixes:
                yield entry


def import_dir(path: str, *, source: str = "courses", recursive: bool = True,
               course: str = "", tags: str = "") -> dict:
    """扫描并入库；返回 `{imported, skipped, failed, scanned, items}`。"""
    text = str(path or "").strip()
    if not text:
        raise ValueError("目录不能为空")
    try:
        target = pathlib.Path(text).expanduser().resolve()
    except (OSError, ValueError) as exc:
        raise ValueError(f"这个目录读不了：{exc}") from exc
    if not target.is_dir():
        raise ValueError("这个目录不存在，或者不是文件夹")

    if source == "obsidian":
        root = obsidian_root()
        if root is None:
            raise ValueError("还没在设置里填 Obsidian 目录（materials.obsidian_dir）")
        if not _within(target, root):
            raise ValueError("只能导入设置里填的那个 Obsidian 目录")
        suffixes = {".md"}
        source_name = "obsidian"
    else:
        roots = allowed_roots()
        if not roots:
            raise ValueError("先去设置里填允许导入的资料目录（materials.import_dirs）")
        if not any(_within(target, item) for item in roots):
            raise ValueError("这个目录不在允许列表里；先到设置里把它加上")
        suffixes = SUFFIXES
        source_name = "import"

    stats = {"imported": 0, "skipped": 0, "failed": 0, "scanned": 0, "items": []}
    raw_dir = pathlib.Path(app_config.materials_dir()) / "原文"
    raw_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect()
    try:
        for file in _iter_files(target, suffixes, recursive):
            if stats["scanned"] >= MAX_FILES:
                break
            stats["scanned"] += 1
            name = file.name
            try:
                blob = file.read_bytes()
            except OSError as exc:
                stats["failed"] += 1
                stats["items"].append({"title": name, "status": "failed", "why": str(exc)})
                continue
            if len(blob) > MAX_BYTES:
                stats["failed"] += 1
                stats["items"].append({"title": name, "status": "failed",
                                       "why": "文件超过 50MB"})
                continue

            sha256 = hashlib.sha256(blob).hexdigest()
            row = conn.execute(
                "SELECT id FROM materials WHERE sha256 = ? AND status = 'active'",
                (sha256,)).fetchone()
            if row is not None:
                stats["skipped"] += 1
                continue

            stored = raw_dir / f"{uuid.uuid4().hex[:16]}{file.suffix.lower()}"
            try:
                stored.write_bytes(blob)
                extracted = study.extract_document(str(stored))
                body = str(extracted.get("text") or "").strip()
                if len(body) < 20:
                    raise ValueError("几乎没读到文字（扫描版需要先 OCR）")
                truncated = len(body) > MAX_TEXT_CHARS
                body = body[:MAX_TEXT_CHARS]
                rel = stored.relative_to(pathlib.Path(app_config.DATA_ROOT)).as_posix()
                item_id, created = store.add_material(
                    conn, title=name, kind=extracted.get("kind") or file.suffix[1:],
                    source=source_name, path=rel, body=body,
                    pages=int(extracted.get("pages") or 0), size=len(blob),
                    sha256=sha256, course=course, tags=tags,
                    meta={"import_from": str(file), "truncated": truncated})
                if created:
                    stats["imported"] += 1
                else:
                    stats["skipped"] += 1
                    stored.unlink(missing_ok=True)
            except Exception as exc:  # 单个文件失败不影响整批
                stored.unlink(missing_ok=True)
                stats["failed"] += 1
                if len(stats["items"]) < 50:
                    stats["items"].append(
                        {"title": name, "status": "failed", "why": str(exc)})
    finally:
        conn.close()
    return stats
