"""Agent 中枢任务队列：唯一的派发入口（P26.3）。

- 任务先落 `queued`，由 `schedule_drain()` 原子认领后启动；
- 每 agent 串行、全局 `max_concurrent`；排队位次见 `store.agent_tasks`；
- 进程重启后首次访问中枢时 `ensure_started()` 把残留 `running` 置失败、
  再让 `queued` 继续排队（`queued` 保证尚未启动）。
"""
from __future__ import annotations

import pathlib
import threading

from learnsys import config as app_config
from learnsys import diagnostics, store

from . import registry, runner

_LOCK = threading.Lock()
_OWNER: int | None = None
_START_LOCK = threading.Lock()
_STARTED = False
_HOOK_BASE = "http://127.0.0.1:8765"


def configure(hook_base: str) -> None:
    """由 `create_app` 注入实际端口，审批钩子才能回调到正确的服务。"""
    global _HOOK_BASE
    base = str(hook_base or "").rstrip("/")
    if base:
        _HOOK_BASE = base


def hook_url() -> str:
    return f"{_HOOK_BASE}/api/agents/hooks/approval"


def recover(conn) -> int:
    """把上次进程残留的 running 标成失败；queued 不动，交给 drain 接续。"""
    task_ids = store.fail_agent_running_tasks(conn, "工作台重启，任务中断")
    for task_id in task_ids:
        try:
            store.add_agent_task_event(
                conn, task_id, 0, "status", "工作台重启，任务已中断")
        except Exception:
            pass
    return len(task_ids)


def ensure_started(db_path: pathlib.Path | None = None) -> None:
    """每进程只跑一次：恢复残留状态，然后派发已有的 queued 任务。"""
    global _STARTED
    if _STARTED:
        return
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
    try:
        conn = store.connect(db_path)
        try:
            recover(conn)
        finally:
            conn.close()
        schedule_drain(db_path)
    except Exception as exc:            # 恢复/派发失败不能挡住中枢
        diagnostics.log_swallow("Agent 中枢：恢复中断任务", exc)


def schedule_drain(db_path: pathlib.Path | None = None) -> None:
    """派发队列；同一线程重入只记一次，由当前循环继续。"""
    global _OWNER
    me = threading.get_ident()
    if _OWNER == me:
        return
    with _LOCK:
        _OWNER = me
        try:
            _drain_once(db_path)
        finally:
            _OWNER = None


def _drain_once(db_path: pathlib.Path | None) -> None:
    conn = store.connect(db_path)
    try:
        settings = registry.settings()
        max_global = registry.max_concurrent(settings)
        while True:
            task_id = store.claim_agent_task(conn, max_global=max_global)
            if task_id is None:
                break
            task = store.get_agent_task(conn, task_id)
            if task is None:            # 理论到不了；认领后不会消失
                break
            spec = registry.spec_for(task["agent"], settings)
            if spec is None or not spec.available:
                reason = (spec.note if spec is not None and spec.note
                          else "这个 agent 现在不可用")
                _fail(conn, task_id, f"排队期间 agent 不可用：{reason}")
                continue
            timeout_s = int(task.get("timeout_s") or 0) or registry.timeout(settings)
            try:
                runner.start_task(
                    task_id, spec, task["prompt"],
                    pathlib.Path(task["workspace"]), timeout_s,
                    app_config.DATA_ROOT, db_path=db_path, mode=task["mode"],
                    hook_url=hook_url(),
                    approval_timeout=registry.approval_timeout(settings),
                    on_finish=lambda path=db_path: schedule_drain(path))
            except Exception as exc:
                _fail(conn, task_id, f"任务启动失败：{exc}")
    finally:
        conn.close()


def cancel(task_id: int, db_path: pathlib.Path | None = None) -> bool:
    """取消任务：与派发共用同一把锁，避免「刚认领、还没注册取消事件」的窗口。"""
    with _LOCK:
        conn = store.connect(db_path)
        try:
            if store.cancel_agent_queued_task(conn, task_id, "用户取消了排队"):
                store.add_agent_task_event(conn, task_id, 0, "status", "已取消排队")
                return True
        finally:
            conn.close()
        return runner.cancel_task(task_id)


def _fail(conn, task_id: int, reason: str) -> None:
    try:
        store.update_agent_task(
            conn, task_id, status="failed", ended_at=store.now(),
            error=reason, duration_ms=0)
        store.add_agent_task_event(conn, task_id, 0, "error", reason)
        store.add_agent_task_event(conn, task_id, 0, "status", "任务失败")
    except Exception as exc:
        diagnostics.log_swallow("Agent 中枢：标记任务失败", exc)
