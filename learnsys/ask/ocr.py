"""快照 OCR：RapidOCR（离线中文识别）后台队列 —— 录屏快照里的文字进库可搜索。

OCR 慢（每张 1~3 秒），所以单独一条线程慢慢啃队列，绝不让录制/界面等它。
文字存 frame_text 表（ts = 快照拍摄时刻），复盘按会话时间窗取用。
"""
from __future__ import annotations

import queue
import threading

from PySide6 import QtCore

from learnsys import store

_engine = None
_engine_error = ""


def _get_engine():
    global _engine, _engine_error
    if _engine is None and not _engine_error:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        except Exception as exc:
            _engine_error = f"{type(exc).__name__}: {exc}"
    if _engine is None:
        raise RuntimeError(_engine_error or "OCR 引擎没起来")
    return _engine


def ocr_image(path: str) -> str:
    """一张图 → 按行拼好的文字（识别失败返回空串）。"""
    result, _elapsed = _get_engine()(path)
    lines = []
    for item in result or []:
        try:
            text = str(item[1]).strip()
        except (IndexError, TypeError):
            continue
        if text:
            lines.append(text)
    return "\n".join(lines)


class OcrQueue(QtCore.QObject):
    """快照路径进队，后台线程 OCR，完成发 text_ready(路径, 文字)。"""

    text_ready = QtCore.Signal(str, str)

    def __init__(self, conn_getter, parent=None):
        super().__init__(parent)
        self._conn_getter = conn_getter
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def enqueue(self, path: str, ts: str) -> None:
        self._queue.put((path, ts))
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="ocr", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            path, ts = item
            try:
                text = ocr_image(path)
            except Exception:
                continue                     # 单张失败别拖垮队列
            if not text:
                continue
            try:
                store.add_frame_text(self._conn_getter(), path, ts, text)
            except Exception:
                continue
            self.text_ready.emit(path, text)
