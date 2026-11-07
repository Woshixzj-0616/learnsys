"""P32 验收闸门：纯确定性检查，不调模型、不读 agent 自述。

派活前记一份工作区快照，任务结束后再记一份，差集就是「这次到底动了什么」。
- 只读任务默认要求**零改动**；
- 可写任务默认要求改动都在工作目录内、文件数不超上限。

判定只看产物。验收自身出错（快照截断、命令超时、契约写错）一律 `error`，
**绝不判通过**——一个证明不了任何事的绿勾比诚实报红更糟。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time

DEFAULT_MAX_FILES = 50
SNAPSHOT_MAX_FILES = 200000
COMMAND_TIMEOUT_S = 120
MAX_VERDICT_JSON = 64000

# 走查目录时跳过：版本库、虚拟环境、前端依赖、构建产物、各种缓存。
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode",
}
EXCLUDED_PREFIX = ("build-", "dist-", "dist_build", "dist-build", "dist\\", "dist/")

# command_zero 只放行这些可执行文件名；不认绝对路径以外的解释器别名。
COMMAND_ALLOW = {"python", "python3", "py", "pytest", "npm", "node"}

CHECKS = ("no_workspace_change", "within_scope", "file_nonempty", "command_zero")


# ---------------------------------------------------------------- 快照与差集

def _normalize_exclude(exclude) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for item in exclude or ():
        try:
            out.append(pathlib.Path(item).resolve())
        except (OSError, ValueError):
            continue
    return out


def _excluded(path: pathlib.Path, roots: list[pathlib.Path]) -> bool:
    """命中排除项本身或其子路径。"""
    for root in roots:
        if path == root:
            return True
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _entries_for(paths: list[str], root: pathlib.Path) -> dict[str, list]:
    """记录 (size, mtime_ns)；文件已消失就记 None。"""
    out: dict[str, list] = {}
    for rel in paths:
        try:
            stat = (root / rel).stat()
            out[rel] = [int(stat.st_size), int(stat.st_mtime_ns)]
        except OSError:
            out[rel] = [0, 0]
    return out


def _snapshot_git(workspace: pathlib.Path, max_files: int,
                  excluded: list[pathlib.Path]) -> dict:
    """git 仓库：只记『工作区已有的改动』，前后两次做差，用户自己的改动不会被算进去。"""
    head = ""
    try:
        head = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        head = ""
    out = subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain=v1", "-z"],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30)
    if out.returncode != 0:
        raise RuntimeError(f"git status 失败：{out.stderr.strip()[:200]}")
    paths: list[str] = []
    parts = (out.stdout or "").split("\0")
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if not entry:
            continue
        # 格式：XY <path>；改名/复制会紧跟一段原路径，要一起跳过。
        code, path = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            index += 1
        if excluded and _excluded((workspace / path).resolve(), excluded):
            continue
        paths.append(path)
        if len(paths) >= max_files:
            return {"kind": "git", "head": head,
                    "entries": _entries_for(paths, workspace), "truncated": True}
    return {"kind": "git", "head": head,
            "entries": _entries_for(paths, workspace), "truncated": False}


def _skipped_dir(name: str) -> bool:
    return name in EXCLUDED_DIRS or name.startswith(EXCLUDED_PREFIX)


def _excluded_str(path_str: str, excluded: list[str]) -> bool:
    """走查热路径用：excluded 已归一化，纯字符串比较，不构造 Path。"""
    low = os.path.normcase(path_str)
    for root in excluded:
        if low == root or low.startswith(root + os.sep):
            return True
    return False


def _snapshot_walk(workspace: pathlib.Path, max_files: int,
                   excluded: list[pathlib.Path]) -> dict:
    """非 git 目录：走一遍工作区，记相对路径与 (size, mtime_ns)。

    用 `os.scandir` 而不是 `os.walk` + `Path.stat()`：Windows 上目录枚举本身
    就带 size/mtime，不必再逐个 stat，实测 7 万文件从 2.7 秒降到 0.65 秒。
    """
    entries: dict[str, list] = {}
    root_str = str(workspace)
    prefix = root_str if root_str.endswith(os.sep) else root_str + os.sep
    excluded_str = [os.path.normcase(str(item)) for item in excluded]
    stack = [root_str]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as items:
                for entry in items:
                    try:
                        if excluded_str and _excluded_str(entry.path, excluded_str):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if not _skipped_dir(entry.name):
                                stack.append(entry.path)
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        rel = entry.path[len(prefix):].replace(os.sep, "/")
                        entries[rel] = [int(stat.st_size), int(stat.st_mtime_ns)]
                    except OSError:
                        continue
                    if len(entries) >= max_files:
                        return {"kind": "walk", "head": "",
                                "entries": entries, "truncated": True}
        except OSError:
            continue
    return {"kind": "walk", "head": "", "entries": entries, "truncated": False}


def snapshot(workspace: str | pathlib.Path,
             max_files: int = SNAPSHOT_MAX_FILES, exclude=()) -> dict:
    """工作区快照。git 仓库优先；git 不可用或目录不存在时直接抛错，由调用方转 error。

    `exclude` 是系统自己的痕迹（数据库 -wal/-shm、任务结果文件），
    默认工作目录就是数据目录，不排除会把它们算成 agent 的改动。
    """
    root = pathlib.Path(workspace)
    if not root.is_dir():
        raise RuntimeError(f"工作目录不存在：{root}")
    max_files = max(1, int(max_files or SNAPSHOT_MAX_FILES))
    excluded = _normalize_exclude(exclude)
    if (root / ".git").exists():
        try:
            return _snapshot_git(root, max_files, excluded)
        except (OSError, subprocess.TimeoutExpired, RuntimeError):
            pass          # git 不可用就退回走查，别让验收挂掉
    return _snapshot_walk(root, max_files, excluded)


def diff_snapshots(before: dict, after: dict) -> dict:
    """两次快照的差集：路径新增/消失/大小或时间变化，都算「动了」。"""
    old = (before or {}).get("entries") or {}
    new = (after or {}).get("entries") or {}
    changed = sorted(path for path in set(old) | set(new) if old.get(path) != new.get(path))
    return {
        "changed": changed,
        "count": len(changed),
        "truncated": bool((before or {}).get("truncated") or (after or {}).get("truncated")),
        "commit_detected": bool(
            (before or {}).get("head") and (after or {}).get("head")
            and before["head"] != after["head"]),
    }


# ---------------------------------------------------------------- 契约

def build_default_contract(mode: str = "read", workspace: str | pathlib.Path = ".",
                           max_files: int = DEFAULT_MAX_FILES) -> dict:
    """不填契约也照样验：只读零改动，可写不越界。"""
    write = str(mode or "read") == "write"
    root = str(pathlib.Path(workspace).resolve())
    return {
        "v": 1,
        "auto": True,
        "scope": {
            "roots": [root],
            "allow_write": write,
            "max_files": max(0, int(max_files)) if write else 0,
        },
        "deliverables": [],
        "acceptance": (
            [{"id": "auto-scope", "check": "within_scope"}]
            if write else
            [{"id": "auto-readonly", "check": "no_workspace_change"},
             {"id": "auto-scope", "check": "within_scope"}]
        ),
        "on_unverifiable": "fail",
    }


def normalize_contract(raw, mode: str = "read", workspace: str | pathlib.Path = ".",
                       max_files: int = DEFAULT_MAX_FILES) -> tuple[dict, str]:
    """返回 (契约, 错误说明)。没给契约时自动生成默认契约。"""
    if isinstance(raw, str):
        if not raw.strip():
            raw = {}
        else:
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return {}, "契约不是合法 JSON"
    if raw in (None, "", {}):
        return build_default_contract(mode, workspace, max_files), ""
    if not isinstance(raw, dict):
        return {}, "契约必须是对象"
    contract = json.loads(json.dumps(raw))            # 深拷贝，别改调用方的对象
    contract.setdefault("v", 1)
    # 已是自动契约（落库后再归一）时保留标记；只有用户手写的才标成手动。
    if "auto" not in contract:
        contract["auto"] = False
    scope = contract.get("scope")
    if not isinstance(scope, dict):
        return {}, "契约缺少 scope"
    roots = scope.get("roots")
    if not isinstance(roots, list) or not roots or not all(isinstance(x, str) for x in roots):
        return {}, "scope.roots 必须是非空字符串数组"
    try:
        scope["max_files"] = max(0, int(scope.get("max_files") or 0))
    except (TypeError, ValueError):
        return {}, "scope.max_files 必须是整数"
    items = contract.get("acceptance")
    if not isinstance(items, list):
        return {}, "acceptance 必须是数组"
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return {}, f"acceptance[{index}] 必须是对象"
        if item.get("check") not in CHECKS:
            return {}, f"acceptance[{index}] 的 check 未知：{item.get('check')}"
        item.setdefault("id", f"a{index + 1}")
    return contract, ""


# ---------------------------------------------------------------- 检查

def _resolve_inside(workspace: pathlib.Path, rel: str) -> pathlib.Path | None:
    """只允许工作区内的相对路径；越界返回 None。"""
    try:
        target = (workspace / str(rel)).resolve()
        target.relative_to(workspace.resolve())
    except (OSError, ValueError):
        return None
    return target


def _check_no_workspace_change(_item: dict, ctx: dict) -> dict:
    changes = ctx["changes"]
    ok = changes["count"] == 0 and not changes["commit_detected"]
    if changes["commit_detected"]:
        detail = "只读任务期间出现了新的提交"
    elif changes["count"]:
        detail = "只读任务改动了工作区：" + "、".join(changes["changed"][:5])
    else:
        detail = ""
    return {"ok": ok, "expected": "0 个改动",
            "actual": f"{changes['count']} 个改动", "detail": detail}


def _within(roots: list[pathlib.Path], path: pathlib.Path) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _check_within_scope(item: dict, ctx: dict) -> dict:
    scope = ctx["contract"].get("scope") or {}
    workspace = ctx["workspace"]
    roots = [pathlib.Path(str(root)).resolve() for root in scope.get("roots") or []]
    max_files = int(scope.get("max_files") or 0)
    changes = ctx["changes"]
    outside = []
    for rel in changes["changed"]:
        target = _resolve_inside(workspace, rel)
        if target is None or not _within(roots, target):
            outside.append(rel)
    over = changes["count"] > max_files
    ok = not outside and not over and not changes["truncated"]
    if changes["truncated"]:
        detail = "快照被截断，无法确认全部改动"
    elif outside:
        detail = "越界：" + "、".join(outside[:5])
    elif over:
        detail = f"改动文件 {changes['count']} 个，超过上限 {max_files}"
    else:
        detail = ""
    return {"ok": ok, "expected": f"≤{max_files} 个文件且都在范围",
            "actual": f"{changes['count']} 个文件", "detail": detail}


def _check_file_nonempty(item: dict, ctx: dict) -> dict:
    rel = str((item.get("args") or {}).get("path") or "")
    target = _resolve_inside(ctx["workspace"], rel) if rel else None
    if target is None:
        return {"ok": False, "expected": "工作区内文件",
                "actual": "路径非法或越界", "detail": rel}
    try:
        size = target.stat().st_size
    except OSError:
        return {"ok": False, "expected": "文件存在且非空",
                "actual": "文件不存在", "detail": rel}
    return {"ok": size > 0, "expected": "文件存在且非空",
            "actual": f"{size} 字节", "detail": "" if size > 0 else "文件为空"}


def _check_command_zero(item: dict, ctx: dict) -> dict:
    argv = (item.get("args") or {}).get("cmd")
    if (not isinstance(argv, list) or not argv
            or not all(isinstance(part, str) for part in argv)):
        return {"ok": False, "expected": "命令数组",
                "actual": "参数非法", "detail": "cmd 必须是字符串数组"}
    name = pathlib.Path(argv[0]).name.lower().removesuffix(".exe")
    if name not in COMMAND_ALLOW:
        return {"ok": False, "expected": f"白名单 {sorted(COMMAND_ALLOW)}",
                "actual": argv[0], "detail": "命令不在允许列表，未执行"}
    started = time.monotonic()
    try:
        done = subprocess.run(
            argv, cwd=str(ctx["workspace"]), timeout=COMMAND_TIMEOUT_S,
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "expected": "退出码 0",
                "actual": f"超时 {COMMAND_TIMEOUT_S} 秒", "detail": "命令超时"}
    except OSError as exc:
        return {"ok": False, "expected": "退出码 0",
                "actual": f"无法执行：{exc}", "detail": "命令启动失败"}
    elapsed = int((time.monotonic() - started) * 1000)
    tail = ((done.stderr or done.stdout or "").strip().splitlines() or [""])[-1][:200]
    return {"ok": done.returncode == 0, "expected": "退出码 0",
            "actual": f"退出码 {done.returncode}（{elapsed} 毫秒）", "detail": tail}


_CHECK_FUNCS = {
    "no_workspace_change": _check_no_workspace_change,
    "within_scope": _check_within_scope,
    "file_nonempty": _check_file_nonempty,
    "command_zero": _check_command_zero,
}


# ---------------------------------------------------------------- 主入口

def _empty_verdict(state: str, detail: str, workspace: str = "") -> dict:
    return {"v": 1, "state": state, "checked_at": _stamp(), "elapsed_ms": 0,
            "workspace": workspace, "changes": {"changed": [], "count": 0,
            "truncated": False, "commit_detected": False},
            "items": [], "summary": detail}


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def invalid(reason: str, workspace: str | pathlib.Path = "") -> dict:
    """契约本身就不合法：判 error，不给任何通过的机会。"""
    return _empty_verdict("error", f"契约无效：{reason}", str(workspace))


def verify(contract, workspace: str | pathlib.Path, before,
           mode: str = "read", max_files: int = DEFAULT_MAX_FILES,
           exclude=()) -> dict:
    """跑全部检查。任何异常都转成 error；没有契约才是 skipped。"""
    workspace = pathlib.Path(workspace)
    if not contract:
        return _empty_verdict("skipped", "没有契约", str(workspace))
    try:
        return _verify_inner(contract, workspace, before, exclude)
    except Exception as exc:          # 验收自己炸了不能拖垮任务落库
        return _empty_verdict("error", f"验收异常：{exc}", str(workspace))


def _verify_inner(contract, workspace: pathlib.Path, before, exclude=()) -> dict:
    if before is not None and not isinstance(before, dict):
        return _empty_verdict("error", "开始快照格式不对", str(workspace))
    started = time.monotonic()
    try:
        after = snapshot(workspace, exclude=exclude)
    except Exception as exc:
        return _empty_verdict("error", f"结束快照失败：{exc}", str(workspace))
    changes = diff_snapshots(before or {}, after)
    ctx = {"workspace": workspace, "changes": changes, "contract": contract}
    items: list[dict] = []
    for item in contract.get("acceptance") or []:
        check = item.get("check")
        func = _CHECK_FUNCS.get(check)
        if func is None:
            items.append({"id": item.get("id"), "check": check, "ok": False,
                          "expected": "", "actual": "", "detail": "未知检查"})
            continue
        try:
            result = func(item, ctx)
        except Exception as exc:          # 单条检查炸了，不能连累整份验收
            result = {"ok": False, "expected": "", "actual": "",
                      "detail": f"检查异常：{exc}"}
        items.append({"id": item.get("id"), "check": check, **result})
    failed = [item for item in items if not item["ok"]]
    if not items:
        state = "error"
        summary = "契约里没有可执行的检查"
    elif changes["truncated"]:
        state = "error"
        summary = "快照被截断，验收不完整"
    elif failed:
        state = "failed"
        summary = f"{len(items) - len(failed)}/{len(items)} 通过"
    else:
        state = "passed"
        summary = f"{len(items)}/{len(items)} 通过"
    verdict = {
        "v": 1, "state": state, "checked_at": _stamp(),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "workspace": str(workspace), "changes": changes,
        "items": items, "summary": summary,
    }
    return verdict


def dumps(verdict: dict) -> str:
    """落库前统一序列化；超长时逐级瘦身，**任何情况下都输出合法 JSON**。"""
    text = json.dumps(verdict, ensure_ascii=False)
    if len(text) <= MAX_VERDICT_JSON:
        return text
    slim = dict(verdict)
    slim["changes"] = dict(verdict.get("changes") or {})
    slim["changes"]["changed"] = (slim["changes"].get("changed") or [])[:50]
    slim["changes"]["truncated"] = True
    slim["items"] = (verdict.get("items") or [])[:20]
    text = json.dumps(slim, ensure_ascii=False)
    if len(text) <= MAX_VERDICT_JSON:
        return text
    # 兜底：只保留状态与摘要，保证「库里有记录」且能解析。
    changes = dict(verdict.get("changes") or {})
    minimal = {
        "v": 1, "state": verdict.get("state"), "summary": verdict.get("summary") or "",
        "checked_at": verdict.get("checked_at") or "",
        "changes": {"changed": [], "count": int(changes.get("count") or 0),
                    "truncated": True,
                    "commit_detected": bool(changes.get("commit_detected"))},
        "items": [], "truncated": True,
    }
    return json.dumps(minimal, ensure_ascii=False)


def loads(raw) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
