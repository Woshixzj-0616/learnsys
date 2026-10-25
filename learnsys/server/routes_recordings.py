"""录像（P23）：列表、详情、视频流、缩略图、幻灯片、打开文件夹、存资料、删除。

视频/缩略图/幻灯片走 `/media/...`（不加令牌）：`<video>`、`<img>` 发不出
`X-Learnsys-Token`，所以按录音 id 取文件、不接受路径参数；和 `/web`、`/cet6/试卷`
一样只在本机监听。
"""
from __future__ import annotations

import pathlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from learnsys import config, store
from learnsys.server.routes_data.common import _conn
from learnsys.server.security import require_token
from learnsys.services import ops, video_analysis

router = APIRouter()


def _video_root() -> pathlib.Path:
    return pathlib.Path(config.VIDEO_DIR)


def _inside_video_root(path: pathlib.Path) -> bool:
    try:
        root = _video_root().resolve()
        target = path.resolve()
        return target != root and target.is_relative_to(root)
    except Exception:
        return False


def _file_for(recording_id: int, kind: str) -> pathlib.Path:
    conn = _conn()
    try:
        item = store.get_recording(conn, recording_id)
    finally:
        conn.close()
    if not item:
        raise HTTPException(status_code=404, detail="没有这段录像")
    raw = item.get("video_path") if kind == "video" else item.get("thumb_path")
    if not raw:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = pathlib.Path(str(raw))
    if not path.is_file() or not _inside_video_root(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return path


@router.get("/api/recordings")
def list_recordings(q: str = "", limit: int = 50, _=Depends(require_token)):
    conn = _conn()
    try:
        return {
            "items": store.list_recordings(conn, query=q, limit=limit),
            "totals": store.recording_totals(conn),
        }
    finally:
        conn.close()


@router.get("/api/recordings/{recording_id}")
def get_recording(recording_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.get_recording(conn, recording_id)
        if item:
            item["analysis"] = video_analysis.latest(conn, recording_id)
    finally:
        conn.close()
    if not item:
        raise HTTPException(status_code=404, detail="没有这段录像")
    return item


@router.post("/api/recordings/{recording_id}/analyze")
def analyze_recording(recording_id: int, force: bool = False,
                      _=Depends(require_token)):
    try:
        return video_analysis.submit(recording_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/recordings/{recording_id}/analysis")
def recording_analysis(recording_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        if store.get_recording(conn, recording_id) is None:
            raise HTTPException(status_code=404, detail="没有这段录像")
        return {"analysis": video_analysis.latest(conn, recording_id)}
    finally:
        conn.close()


@router.post("/api/recordings/{recording_id}/analysis/cancel")
def cancel_analysis(recording_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        row = video_analysis.latest(conn, recording_id)
        if not row:
            raise HTTPException(status_code=404, detail="还没有分析任务")
        return {"ok": video_analysis.cancel(int(row["id"]))}
    finally:
        conn.close()


@router.get("/media/recordings/{recording_id}/video.mp4", include_in_schema=False)
def video(recording_id: int):
    path = _file_for(recording_id, "video")
    return FileResponse(str(path), media_type="video/mp4")


@router.get("/media/recordings/{recording_id}/thumb.jpg", include_in_schema=False)
def thumb(recording_id: int):
    path = _file_for(recording_id, "thumb")
    return FileResponse(str(path), media_type="image/jpeg")


@router.get("/media/recordings/{recording_id}/slides/{name}", include_in_schema=False)
def slide(recording_id: int, name: str):
    if ("/" in name or "\\" in name or name.startswith(".")
            or ".." in name or not name.lower().endswith(".jpg")):
        raise HTTPException(status_code=404, detail="文件不存在")
    conn = _conn()
    try:
        item = store.get_recording(conn, recording_id)
    finally:
        conn.close()
    if not item or not item.get("slides_dir"):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = pathlib.Path(str(item["slides_dir"])) / name
    if not path.is_file() or not _inside_video_root(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(str(path), media_type="image/jpeg")


@router.post("/api/recordings/open-root")
def open_root(_=Depends(require_token)):
    root = _video_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        message = ops.open_path(str(root))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": message, "folder": str(root)}


@router.post("/api/recordings/{recording_id}/open-folder")
def open_folder(recording_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.get_recording(conn, recording_id)
    finally:
        conn.close()
    if not item:
        raise HTTPException(status_code=404, detail="没有这段录像")
    folder = ""
    for raw in (item.get("video_path"), item.get("slides_dir")):
        if raw:
            folder = str(pathlib.Path(str(raw)).parent)
            break
    if not folder or not pathlib.Path(folder).is_dir() or not _inside_video_root(pathlib.Path(folder)):
        raise HTTPException(status_code=404, detail="录像文件夹不存在")
    try:
        message = ops.open_path(folder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": message, "folder": folder}


@router.post("/api/recordings/{recording_id}/material")
def save_material(recording_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.get_recording(conn, recording_id)
        if not item:
            raise HTTPException(status_code=404, detail="没有这段录像")
        existing = int(item.get("material_id") or 0)
        if existing:
            material = store.get_material(conn, existing)
            if material and material.get("status") == "active":
                return {"ok": True, "created": False, "item": material}
        text = store.recording_transcript(conn, recording_id, cap=60000)
        body = (f"# {item['title']}\n\n"
                f"> 录像：{item['started_at']} · {item['duration']:.1f} 秒\n\n"
                f"{text or '（这段还没有转写）'}\n")
        item_id, created = store.add_material(
            conn, title=item["title"], kind="note", source="video", body=body,
            tags="录像", meta={"session_id": int(recording_id),
                              "video_path": item.get("video_path") or ""})
        store.set_recording_material(conn, recording_id, item_id)
        return {"ok": True, "created": created,
                "item": store.get_material(conn, item_id)}
    finally:
        conn.close()


@router.delete("/api/recordings/{recording_id}")
def delete_recording(recording_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        result = store.delete_recording(conn, recording_id, remove_files=True)
    finally:
        conn.close()
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error") or "没有这段录像")
    return result
