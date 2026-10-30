"""生活订阅调度：到期 → 生成 → 落卡 → 记 `last_run`。

线程口径照 `services/briefing/runner.py`：启动后 30 秒首检，之后每 5 分钟一次；
测试进程（`unittest` 已加载）不启动线程，测试直接调 `tick()`。

失败分三类：
- `LifeNotReady`：前置资料未就绪，**不记时间、不退避**，下个 tick 再来；
- `LifeUnsupported`：本轮不支持的订阅类型，记一次 `last_run`，当天不再重试；
- 其它异常：退避 30 分钟，避免模型故障时每 5 分钟烧一次调用。
"""
from __future__ import annotations

import datetime as dt
import sys
import threading

from learnsys import diagnostics, store

from . import cards

FIRST_DELAY = 30
INTERVAL = 300
RETRY_MINUTES = 30

_STOP = threading.Event()
_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_FAILED_UNTIL: dict[int, dt.datetime] = {}


def _stamp(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _mark(conn, sub: dict, moment: dt.datetime) -> None:
    try:
        store.mark_run(conn, sub["id"], ts=_stamp(moment))
    except Exception as exc:  # noqa: BLE001 —— 记时间失败不应中断其它订阅
        diagnostics.log_swallow("生活订阅：记运行时间", exc)


def tick(now: dt.datetime | None = None) -> None:
    """一次调度检查；测试直接调它，不用等线程。"""
    moment = now or dt.datetime.now()
    conn = store.connect()
    try:
        due = store.due_subscriptions(conn, at=moment)
        for sub in due:
            sub_id = int(sub["id"])
            if _FAILED_UNTIL.get(sub_id, dt.datetime.min) > moment:
                continue
            try:
                cards.generate(conn, sub, moment.date().isoformat())
            except cards.LifeNotReady:
                continue
            except cards.LifeUnsupported as exc:
                diagnostics.log_swallow("生活订阅：不支持的类型", exc)
                _mark(conn, sub, moment)
                continue
            except Exception as exc:  # noqa: BLE001 —— 一条失败不连带其它订阅
                _FAILED_UNTIL[sub_id] = moment + dt.timedelta(minutes=RETRY_MINUTES)
                diagnostics.log_swallow("生活订阅：生成卡片", exc)
                continue
            _FAILED_UNTIL.pop(sub_id, None)
            _mark(conn, sub, moment)
    finally:
        conn.close()


def _scheduler_loop() -> None:
    if _STOP.wait(FIRST_DELAY):
        return
    while not _STOP.is_set():
        try:
            tick()
        except Exception as exc:  # noqa: BLE001 —— 调度线程不能死
            diagnostics.log_swallow("生活订阅：调度检查", exc)
        if _STOP.wait(INTERVAL):
            return


def _is_test_process() -> bool:
    return "unittest" in sys.modules


def ensure_started() -> None:
    if _is_test_process():
        return
    global _THREAD
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _STOP.clear()
            _THREAD = threading.Thread(target=_scheduler_loop,
                                       name="life-scheduler", daemon=True)
            _THREAD.start()


def shutdown() -> None:
    global _THREAD
    _STOP.set()
    with _LOCK:
        thread, _THREAD = _THREAD, None
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)
