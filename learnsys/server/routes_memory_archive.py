"""对话总汇：状态查询与一次性构建入口。"""
from __future__ import annotations

import datetime as dt
import pathlib
import threading

from fastapi import APIRouter, Depends

from learnsys import config, store
from learnsys.server.security import require_token
from learnsys.services.dialog_archive import search as archive_search
from learnsys.services.dialog_archive.build import build_archive, verify_archive
from learnsys.store import memory_batches

router = APIRouter()
_LOCK = threading.Lock()
_STATE: dict = {"running": False, "result": {}, "error": ""}


def _build(data_root: str) -> None:
    try:
        result = build_archive(data_root)
        if not result.get("already_sealed"):
            conn = store.connect(pathlib.Path(data_root) / "learning.db")
            try:
                memory_batches.create_batch(
                    conn, "dialog_archive", status="sealed",
                    archive_id=result.get("archive_id", ""),
                    archive_path=result.get("path", ""),
                    body_sha256=result.get("body_sha256", ""),
                    file_sha256=result.get("file_sha256", ""),
                    stats_json={"sources": result.get("sources", [])},
                    missing_json=result.get("missing", []),
                    finished_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            finally:
                conn.close()
        _STATE["result"] = result
        _STATE["error"] = ""
    except Exception as exc:  # noqa: BLE001
        _STATE["error"] = str(exc)
    finally:
        _STATE["running"] = False


@router.get("/api/memory/archive/status")
def archive_status(_=Depends(require_token)):
    conn = store.connect()
    try:
        batch = memory_batches.find_sealed(conn, "dialog_archive")
    finally:
        conn.close()
    return {"running": _STATE["running"], "result": _STATE["result"],
            "error": _STATE["error"], "batch": batch}


@router.post("/api/memory/archive/build")
def archive_build(_=Depends(require_token)):
    with _LOCK:
        if _STATE["running"]:
            return {"ok": False, "message": "正在构建，请稍后再看"}
        _STATE["running"] = True
        _STATE["error"] = ""
        threading.Thread(target=_build, args=(str(config.DATA_ROOT),),
                         daemon=True).start()
    return {"ok": True, "message": "已开始构建；完成后状态会自动更新"}


@router.get("/api/memory/archive/search")
def archive_search_api(q: str = "", limit: int = 8,
                       _=Depends(require_token)):
    path = archive_search.latest_archive(config.DATA_ROOT)
    if path is None:
        return {"items": [], "message": "还没有封存的对话总汇"}
    return {"items": archive_search.search_archive(path, q, limit=limit)}


@router.get("/api/memory/archive/message")
def archive_message_api(anchor: str = "", _=Depends(require_token)):
    path = archive_search.latest_archive(config.DATA_ROOT)
    if path is None:
        return {"ok": False, "reason": "还没有封存的对话总汇"}
    item = archive_search.read_message(path, anchor)
    if item is None:
        return {"ok": False, "reason": "没有找到这个锚点"}
    return {"ok": True, "item": item}


@router.get("/api/memory/archive/verify")
def archive_verify(path: str = "", _=Depends(require_token)):
    if not path:
        conn = store.connect()
        try:
            batch = memory_batches.find_sealed(conn, "dialog_archive")
        finally:
            conn.close()
        path = str((batch or {}).get("archive_path") or "")
    if not path:
        return {"ok": False, "reason": "还没有封存档案"}
    return verify_archive(path)
