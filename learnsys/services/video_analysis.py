"""录像分析（P23 M2）：转写 + 幻灯片 OCR → Markdown 提纲 / 要点 / 术语。

- 结果落 `service_results`（`kind=video_analyze`），页面按 id 轮询；
- 同时写 `<录像目录>/analysis.md`，并存一份资料（`source=video`）供搜索/出题；
- 单独一条 worker，不堵六级分析；
- OCR 缺失的幻灯片由本任务补（RapidOCR 与快捷栏 OCR 队列共用一把引擎锁）。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import queue
import threading
import time

from learnsys import agent, config, diagnostics, store
from learnsys.llm.config import load_config
from learnsys.services import observability, results
from learnsys.services.ocr import ocr_image

ANALYSIS_KIND = "video_analyze"
PROMPT_VERSION = "video-analyze-v1"
ANALYSIS_TIMEOUT = 300.0
TRANSCRIPT_CAP = 60000
OCR_CAP = 20000
OCR_SLIDE_MAX = 120

SYSTEM = "你是严谨、具体的学习教练。你只输出 Markdown，不输出 JSON、代码围栏或额外解释。"

PROMPT_RULES = """下面是一段网课/视频课的自动转写（按时间）和幻灯片 OCR（按时间）。
转写可能有个别识别错误；幻灯片 OCR 可能漏字。没有依据的内容不要编。
请输出 Markdown，严格按这五节：

## 这段课讲了什么
（2–3 句）

## 时间线提纲
（按时间分段，每段 1–2 句，带起始时间；3–8 段）

## 关键要点
（最多 10 条）

## 术语表
（Markdown 表格：术语 | 解释；最多 10 行）

## 没讲清 / 值得追问的地方
（最多 3 条）
"""

_QUEUE: "queue.Queue[tuple[int, int]]" = queue.Queue()
_WORKER: threading.Thread | None = None
_ABORTS: dict[int, threading.Event] = {}
_LOCK = threading.Lock()
_RECOVERED = False


def _analysis_cfg():
    """录像分析走「分析」路由；不思考，省钱也够用。"""
    cfg = load_config()
    return dataclasses.replace(
        cfg,
        model=cfg.model_for("analyze") or cfg.fast_model or cfg.model,
        speed="balanced",
        thinking=False,
    )


def context_hash(session_id: int, transcript: str, slides: list[dict]) -> str:
    payload = (f"{int(session_id)}\n{transcript}\n"
               + "\n".join(str(slide.get("name") or "") for slide in slides))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def slides_digest(slides: list[dict], cap: int = OCR_CAP) -> str:
    pieces = []
    for slide in slides:
        text = " ".join(str(slide.get("text") or "").split())
        if not text:
            continue
        stamp = str(slide.get("ts") or "")
        clock = stamp[11:16] if len(stamp) >= 16 else str(slide.get("name") or "")
        pieces.append(f"[{clock}] {text}")
    joined = "\n".join(pieces)
    return joined[:cap].rstrip()


def build_prompt(rec: dict, transcript: str, slides_text: str) -> str:
    parts = [
        f"【录像】{rec.get('title') or '录像'} · {rec.get('started_at') or ''} · "
        f"{float(rec.get('duration') or 0):.0f} 秒",
        PROMPT_RULES,
        "",
        "【转写】",
        (transcript or "（没有转写）")[:TRANSCRIPT_CAP],
    ]
    if slides_text:
        parts += ["", "【幻灯片 OCR】", slides_text]
    return "\n".join(parts)


def _fill_ocr(conn, session_id: int, slides: list[dict]) -> list[dict]:
    """给还没有 OCR 文字的幻灯片补识别；每张 1–3 秒，设上限。"""
    filled = 0
    for slide in slides:
        if slide.get("text") or filled >= OCR_SLIDE_MAX:
            continue
        try:
            text = ocr_image(str(slide.get("path") or ""))
        except Exception as exc:
            diagnostics.log_swallow("录像分析：OCR 幻灯片", exc)
            continue
        filled += 1
        if not text:
            continue
        slide["text"] = text
        try:
            store.add_frame_text(conn, str(slide["path"]),
                                 str(slide.get("ts") or store.now()), text,
                                 session_id=session_id)
        except Exception as exc:
            diagnostics.log_swallow("录像分析：写幻灯片 OCR", exc)
    return slides


def _usage(raw: dict) -> tuple[int, int]:
    raw = raw if isinstance(raw, dict) else {}
    return (int(raw.get("input_tokens") or raw.get("prompt_tokens") or 0),
            int(raw.get("output_tokens") or raw.get("completion_tokens") or 0))


def _generate(prompt: str, cfg, abort: threading.Event) -> tuple[str, str, dict]:
    return agent.complete(prompt, system_override=SYSTEM,
                          cfg=cfg, abort=abort, mode="quick")


def _ensure_worker() -> None:
    global _WORKER, _RECOVERED
    if not _RECOVERED:
        _RECOVERED = True
        try:
            conn = store.connect()
            try:
                results.recover_orphans(conn, kind=ANALYSIS_KIND)
            finally:
                conn.close()
        except Exception as exc:
            diagnostics.log_swallow("录像分析：恢复孤儿任务", exc)
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="video-analysis",
                                       daemon=True)
            _WORKER.start()


def _worker_loop() -> None:
    while True:
        result_id, session_id = _QUEUE.get()
        try:
            run_job(result_id, session_id)
        except Exception as exc:
            diagnostics.log_swallow("录像分析：worker 单条任务", exc)
        finally:
            _QUEUE.task_done()


def submit(session_id: int, *, force: bool = False) -> dict:
    """建任务；同样的输入直接命中旧结果（除非 force）。"""
    conn = store.connect()
    try:
        rec = store.get_recording(conn, int(session_id))
        if rec is None:
            raise ValueError("没有这段录像")
        transcript = store.recording_transcript(
            conn, int(session_id), cap=TRANSCRIPT_CAP)
        slides = store.recording_slides(conn, int(session_id))
        digest = context_hash(int(session_id), transcript, slides)
        cfg = _analysis_cfg()
        _ensure_worker()
        key = dict(kind=ANALYSIS_KIND, target_type="recording",
                   target_id=str(int(session_id)), scope="recording",
                   context_hash=digest, prompt_version=PROMPT_VERSION)
        if not force:
            done = results.find_done(conn, **key)
            if done:
                results.update(conn, done["id"], cache_hit=1)
                return {"id": done["id"], "status": "done", "cached": True}
            active = results.find_by_key(conn, **key)
            if active and active["status"] in ("pending", "running"):
                return {"id": active["id"], "status": active["status"],
                        "cached": True}
            if active and active["status"] in ("error", "canceled"):
                # 失败后直接重试：同 key 的旧行先退休，才能建新的 pending
                results.mark_superseded(conn, **key)
        else:
            results.mark_superseded(conn, **key)
        result_id, created = results.create(
            conn, **key, model=cfg.model,
            input_json=json.dumps({"session_id": int(session_id),
                                   "title": rec.get("title") or "",
                                   "chars": len(transcript),
                                   "slides": len(slides)}, ensure_ascii=False))
        if not created:
            row = results.get(conn, result_id)
            return {"id": result_id,
                    "status": (row or {}).get("status", "pending"),
                    "cached": True}
    finally:
        conn.close()
    _QUEUE.put((result_id, int(session_id)))
    return {"id": result_id, "status": "pending", "cached": False}


def latest(conn, session_id: int) -> dict | None:
    data = results.list_results(
        conn, kind=ANALYSIS_KIND, target_type="recording",
        target_id=str(int(session_id)), scope="recording", limit=1)
    return data["items"][0] if data["items"] else None


def cancel(result_id: int) -> bool:
    conn = store.connect()
    try:
        row = results.get(conn, result_id)
        if not row or row["status"] not in ("pending", "running"):
            return False
        with _LOCK:
            event = _ABORTS.get(result_id)
            if event is not None:
                event.set()
        results.update(conn, result_id, status="canceled", error="")
        return True
    finally:
        conn.close()


def _inside_video_root(path: pathlib.Path) -> bool:
    try:
        root = pathlib.Path(config.VIDEO_DIR).resolve()
        target = path.resolve()
        return target.is_relative_to(root)
    except Exception:
        return False


def _analysis_folder(rec: dict) -> pathlib.Path | None:
    for raw in (rec.get("video_path"), rec.get("slides_dir")):
        if raw:
            folder = pathlib.Path(str(raw)).parent
            if _inside_video_root(folder):
                return folder
    return None


def _save_material(conn, rec: dict, analysis: str, transcript: str) -> int:
    """把分析 + 转写存成资料；已有转写资料时不覆盖，另存一份分析。"""
    title = f"{rec.get('title') or '录像'} · 分析"
    body = (f"# {title}\n\n{analysis.strip()}\n\n---\n\n## 录像转写\n\n"
            f"{transcript.strip()[:TRANSCRIPT_CAP]}\n")
    item_id, created = store.add_material(
        conn, title=title, kind="note", source="video", body=body,
        tags="录像 分析",
        meta={"session_id": int(rec["id"]),
              "video_path": rec.get("video_path") or ""})
    if created and not int(rec.get("material_id") or 0):
        store.set_recording_material(conn, int(rec["id"]), item_id)
    return int(item_id or 0)


def run_job(result_id: int, session_id: int) -> None:
    conn = store.connect()
    try:
        if not results.claim(conn, result_id):
            return
        results.update(conn, result_id, error="")
        rec = store.get_recording(conn, int(session_id))
        if rec is None:
            results.update(conn, result_id, status="error", error="录像不存在")
            return
        transcript = store.recording_transcript(
            conn, int(session_id), cap=TRANSCRIPT_CAP)
        slides = store.recording_slides(conn, int(session_id))
        abort = threading.Event()
        with _LOCK:
            _ABORTS[result_id] = abort
        slides = _fill_ocr(conn, int(session_id), slides)
        slides_text = slides_digest(slides)
        if abort.is_set():
            results.update(conn, result_id, status="canceled", error="")
            return
        if not transcript.strip() and not slides_text.strip():
            results.update(
                conn, result_id, status="error",
                error="这段没有转写也没有幻灯片文字 —— 先确认录到了声音/画面。")
            return
        cfg = _analysis_cfg()
        run_id = observability.start_run(
            surface="video", kind=ANALYSIS_KIND, model=cfg.model,
            result_id=result_id, meta={"session_id": int(session_id)}, conn=conn)
        started = time.monotonic()
        timed_out = {"value": False}

        def on_timeout() -> None:
            timed_out["value"] = True
            abort.set()

        timer = threading.Timer(ANALYSIS_TIMEOUT, on_timeout)
        timer.daemon = True
        timer.start()
        status, error, text, usage = "error", "", "", {}
        try:
            text, error, usage = _generate(
                build_prompt(rec, transcript, slides_text), cfg, abort)
            if abort.is_set() and not text.strip():
                status = "canceled" if not timed_out["value"] else "error"
                error = "分析超时" if timed_out["value"] else ""
            elif error:
                status = "error"
            elif not text.strip():
                status, error = "error", "模型返回了空内容"
            else:
                status = "done"
        except Exception as exc:
            status, error = "error", str(exc)[:500]
        finally:
            timer.cancel()
        current = results.get(conn, result_id)
        if current and current["status"] == "canceled":
            status, error = "canceled", ""
        content = None
        if status == "done":
            folder = _analysis_folder(rec)
            md_path = ""
            if folder is not None:
                try:
                    dest = folder / "analysis.md"
                    dest.write_text(text.strip() + "\n", encoding="utf-8")
                    md_path = str(dest)
                except OSError as exc:
                    diagnostics.log_swallow("录像分析：写 analysis.md", exc)
            material_id = 0
            try:
                material_id = _save_material(conn, rec, text, transcript)
            except Exception as exc:
                diagnostics.log_swallow("录像分析：存资料", exc)
            content = {"markdown": text.strip(), "material_id": material_id,
                       "md_path": md_path}
        ms = int((time.monotonic() - started) * 1000)
        tokens_in, tokens_out = _usage(usage)
        results.update(
            conn, result_id, status=status, error=error, model=cfg.model, ms=ms,
            tokens_in=tokens_in, tokens_out=tokens_out,
            content_json=json.dumps(content, ensure_ascii=False) if content else "")
        observability.finish_run(
            run_id, status=status, ms=ms, tokens_in=tokens_in,
            tokens_out=tokens_out, error=error, conn=conn)
        if status == "done":
            store.set_recording_analysis(conn, int(session_id), result_id)
    finally:
        with _LOCK:
            _ABORTS.pop(result_id, None)
        conn.close()
