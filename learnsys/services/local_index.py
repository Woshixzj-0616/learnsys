"""本机可读目录的后台增量索引（P34.2）。

唯一扫描落点：白名单目录 → `local_files` 表；搜索只查表，不再按需扫盘。
线程口径照 `services/life/scheduler.py`：启动后 5 秒首扫，之后按间隔检查；
测试进程（`unittest` 已加载）不启动线程，测试直接调 `tick()` / `reconcile()`。

安全口径不变：只索引元数据；敏感文件、排除目录、深于 `MAX_DEPTH` 的目录不入库。
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import threading

from learnsys import config, diagnostics, store

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

MAX_DEPTH = 12
MAX_INDEX_ENTRIES = 200_000
BATCH = 200
FIRST_DELAY = 5
DEFAULT_INTERVAL = 120
MIN_INTERVAL = 30
MAX_INTERVAL = 3600

_STOP = threading.Event()
_WAKE = threading.Event()
_STATE_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_FORCE = False
_ROOT_LOCKS: dict[str, threading.Lock] = {}
_SCANNING_ROOTS: set[str] = set()


# ---------------------------------------------------------------- 白名单与路径

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
        candidate = root / path
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


# ---------------------------------------------------------------- 扫描与同步

def _stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _age_seconds(scanned_at: str) -> float | None:
    try:
        moment = dt.datetime.strptime(str(scanned_at), "%Y-%m-%d %H:%M:%S.%f")
    except (TypeError, ValueError):
        return None
    return (dt.datetime.now() - moment).total_seconds()


def _iter_files(root: pathlib.Path, state: dict):
    """逐个产出文件元数据；`state["truncated"]` 表示触到单根上限。

    Windows 不区分大小写，但这里保留原始路径；匹配用 casefold 列。
    """
    stack: list[tuple[pathlib.Path, int]] = [(root, 0)]
    while stack:
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
                        if state["count"] >= MAX_INDEX_ENTRIES:
                            state["truncated"] = True
                            return
                        name = entry.name
                        yield (str(path), name, name.casefold(),
                               str(path).casefold(), path.suffix.casefold(),
                               int(stat.st_size), int(stat.st_mtime_ns))
                        state["count"] += 1
                    except OSError:
                        continue
        except OSError:
            continue


def _root_lock(key: str) -> threading.Lock:
    with _STATE_LOCK:
        lock = _ROOT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _ROOT_LOCKS[key] = lock
        return lock


def reconcile(root: pathlib.Path, *, max_age: float = 0.0) -> dict | None:
    """增量同步一个目录；`max_age` 秒内刚扫过就跳过。

    返回根状态；扫描被截断时不删除旧行（避免把没扫到的文件误删）。
    """
    key = str(root)
    lock = _root_lock(key)
    lock.acquire()
    try:
        conn = store.connect()
        try:
            previous = store.local_file_root_status(conn, key)
            if max_age > 0 and previous:
                age = _age_seconds(previous.get("scanned_at", ""))
                if age is not None and age < max_age:
                    return previous
            if not root.is_dir():
                count = int((previous or {}).get("file_count") or 0)
                store.put_local_file_root_status(
                    conn, key, scanned_at="", file_count=count,
                    status="missing", note="目录不存在或暂时不可用")
                return store.local_file_root_status(conn, key)

            with _STATE_LOCK:
                _SCANNING_ROOTS.add(key)
            stamp = _stamp()
            state = {"count": 0, "truncated": False}
            batch: list[tuple] = []
            for (path, name, name_l, path_l, ext, size, mtime_ns) in _iter_files(root, state):
                batch.append((key, path, name, name_l, path_l, ext, size,
                              mtime_ns, stamp))
                if len(batch) >= BATCH:
                    store.upsert_local_file_entries(conn, batch)
                    batch = []
            if batch:
                store.upsert_local_file_entries(conn, batch)
            if not state["truncated"]:
                store.delete_unseen_local_files(conn, key, stamp)
            status = "truncated" if state["truncated"] else "ok"
            note = (f"文件超过 {MAX_INDEX_ENTRIES} 个，只索引了前 {MAX_INDEX_ENTRIES} 个"
                    if state["truncated"] else "")
            store.put_local_file_root_status(
                conn, key, scanned_at=stamp, file_count=state["count"],
                status=status, note=note)
            return store.local_file_root_status(conn, key)
        finally:
            conn.close()
            with _STATE_LOCK:
                _SCANNING_ROOTS.discard(key)
    except Exception as exc:  # noqa: BLE001 —— 单个目录失败不能拖垮其它目录
        diagnostics.log_swallow("本机文件索引：扫描目录", exc)
        try:
            conn = store.connect()
            try:
                store.put_local_file_root_status(
                    conn, key, scanned_at="", file_count=0,
                    status="error", note=str(exc)[:200])
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            pass
        return None
    finally:
        lock.release()


def _interval() -> int:
    section = config.USER.get("materials")
    raw = section.get("index_refresh_s") if isinstance(section, dict) else None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL
    return max(MIN_INTERVAL, min(MAX_INTERVAL, value))


def tick(_now: dt.datetime | None = None) -> None:
    """一次调度检查；测试直接调它，不用等线程。"""
    roots_now = roots()
    configured = {str(root) for root in roots_now}
    conn = store.connect()
    try:
        statuses = store.local_file_root_statuses(conn)
    finally:
        conn.close()

    for known in list(statuses):
        if known not in configured:
            conn = store.connect()
            try:
                store.delete_local_file_root(conn, known)
            finally:
                conn.close()

    interval = _interval()
    for root in roots_now:
        key = str(root)
        row = statuses.get(key)
        if row is None:
            reconcile(root)
            continue
        if row.get("status") == "missing" and not root.is_dir():
            continue
        age = _age_seconds(row.get("scanned_at", ""))
        if age is None or age >= interval:
            reconcile(root, max_age=interval)


def search(query: str = "", limit: int = 10, suffix: str = "") -> dict:
    """查索引；返回 {roots, entries, total}，entries 为 (path, size, mtime_ns)。

    某个根从未扫过时同步补扫一次（2.64 升级后的首次查询），之后都靠后台线程。
    """
    roots_now = roots()
    if not roots_now:
        return {"roots": [], "entries": [], "total": 0, "matched": 0}

    conn = store.connect()
    try:
        statuses = store.local_file_root_statuses(conn)
    finally:
        conn.close()
    for root in roots_now:
        if str(root) not in statuses:
            reconcile(root, max_age=30)

    tokens = [part for part in str(query or "").casefold().split() if part]
    needle = str(suffix or "").strip().casefold()
    if needle and not needle.startswith("."):
        needle = "." + needle
    try:
        size = max(1, min(int(limit or 10), 20))
    except (TypeError, ValueError):
        size = 10

    conn = store.connect()
    try:
        rows, total, matched = store.search_local_files_index(
            conn, tokens, needle, size)
    finally:
        conn.close()
    return {
        "roots": [str(root) for root in roots_now],
        "entries": [tuple(row) for row in rows],
        "total": int(total),
        "matched": int(matched),
    }


def status() -> dict:
    roots_now = roots()
    conn = store.connect()
    try:
        rows = store.local_file_root_statuses(conn)
    finally:
        conn.close()
    with _STATE_LOCK:
        scanning_roots = set(_SCANNING_ROOTS)
    out = []
    total = 0
    for root in roots_now:
        key = str(root)
        row = rows.get(key) or {
            "root": key, "scanned_at": "", "file_count": 0,
            "status": "pending", "note": "还没有建立索引",
        }
        item = dict(row)
        item["scanning"] = key in scanning_roots
        total += int(item.get("file_count") or 0)
        out.append(item)
    return {
        "ok": True,
        "scanning": bool(scanning_roots),
        "total": total,
        "interval_s": _interval(),
        "roots": out,
    }


# ---------------------------------------------------------------- 调度线程

def _take_force() -> bool:
    global _FORCE
    with _STATE_LOCK:
        force, _FORCE = _FORCE, False
    return force


def _scheduler_loop() -> None:
    if _STOP.wait(FIRST_DELAY):
        return
    while not _STOP.is_set():
        try:
            if _take_force():
                for root in roots():
                    reconcile(root, max_age=0)
            else:
                tick()
        except Exception as exc:  # noqa: BLE001 —— 调度线程不能死
            diagnostics.log_swallow("本机文件索引：调度检查", exc)
        _WAKE.wait(_interval())
        _WAKE.clear()


def _is_test_process() -> bool:
    return "unittest" in sys.modules


def ensure_started() -> None:
    if _is_test_process():
        return
    global _THREAD
    with _STATE_LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _STOP.clear()
            _THREAD = threading.Thread(target=_scheduler_loop,
                                       name="local-index", daemon=True)
            _THREAD.start()


def shutdown() -> None:
    global _THREAD
    _STOP.set()
    _WAKE.set()
    with _STATE_LOCK:
        thread, _THREAD = _THREAD, None
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)


def wake() -> None:
    """白名单变更后叫醒线程，立即处理新增/移除的目录。"""
    _WAKE.set()


def rebuild() -> None:
    """强制重扫所有目录（设置页「立即更新」）。"""
    global _FORCE
    with _STATE_LOCK:
        _FORCE = True
    _WAKE.set()
