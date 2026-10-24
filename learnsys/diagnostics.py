"""静默异常的留痕口：核心层不能吞掉写库/写文件/审计失败。

这些地方故意不让异常冒到界面（一条流水写失败不能盖掉答案），但也不能
完全无声 —— 统一写到 `<数据目录>/启动错误.log`，和启动期异常同一个文件。
日志本身失败只能再吞掉：没有更可靠的落点了。
"""
from __future__ import annotations

import datetime
import pathlib
import threading
import traceback

from learnsys import config

_LOCK = threading.Lock()
LOG_NAME = "启动错误.log"
MAX_BYTES = 2 * 1024 * 1024


def log_path(data_root: pathlib.Path | str | None = None) -> pathlib.Path:
    return pathlib.Path(data_root or config.DATA_ROOT) / LOG_NAME


def log_swallow(context: str, exc: BaseException,
                *, data_root: pathlib.Path | str | None = None) -> None:
    """记录一次被有意吞掉的异常；`context` 写清在哪一步（中文）。"""
    try:
        path = log_path(data_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            try:
                if path.exists() and path.stat().st_size > MAX_BYTES:
                    path.replace(path.with_name("启动错误-上次.log"))
            except OSError:
                pass
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
                         f" · {context} =====\n")
                fh.write("".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        pass          # 日志都写不了时没有更可靠的落点，只能到此为止
