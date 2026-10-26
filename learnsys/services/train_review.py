"""写作/翻译批改任务：后台队列 + 结果资产 + 单句同步审核。

口径来自 `docs/施工单/P24-六级写作翻译训练.md`：
- 整篇（写作/翻译）跑 **3 次取中位**，档位差 >1 标“不稳定”；
- 单句只跑 **1 次**，目标 2 秒内返回；
- 每条错误的 quote 由 `train.review` 逐条核对，伪造的直接丢弃；
- 结果落 `service_results`（kind=`writing_review` / `translation_review` /
  `sentence_review`），页面按 id 轮询；
- 成本由 `agent.run` 内部记入 `model_usage`，这里只汇总 token 与耗时。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import queue
import threading
import time

from learnsys import agent, diagnostics, store
from learnsys.core.jsontext import parse_object
from learnsys.llm.config import load_config
from learnsys.services import observability, results
from learnsys.train import content, prompts, review, rubric

KINDS = {
    "writing": "writing_review",
    "translation": "translation_review",
    "sentence": "sentence_review",
}
SAMPLE_COUNT = {"writing": 3, "translation": 3, "sentence": 1}
TIMEOUT = {"writing": 120.0, "translation": 120.0, "sentence": 30.0}
PROMPT_VERSION = prompts.PROMPT_VERSION
MAX_TEXT = 8000

STRICT_SUFFIX = (
    "\n\n注意：只输出一个合法 JSON 对象；字符串内部的双引号必须转义成 \\\"，"
    "不要输出 Markdown 代码块或任何解释。")

_QUEUE: "queue.Queue[tuple[int, dict]]" = queue.Queue()
_WORKER: threading.Thread | None = None
_ABORTS: dict[int, threading.Event] = {}
_LOCK = threading.Lock()
_RECOVERED = False


def _review_cfg() -> tuple:
    """批改用快模型、不思考；设置里的 `agent.routes.review` 可显式指定。"""
    cfg = load_config()
    routed = cfg.model_for("review")
    model = routed or cfg.fast_model or cfg.model
    routes = dict(cfg.routes or {})
    if routed:
        # quick 模式本会退到 fast_model；把 review 指定的模型钉到 quick 上
        routes["quick"] = model
    return dataclasses.replace(
        cfg, routes=routes, model=model, speed="balanced", thinking=False), model


def _digest(*parts) -> str:
    payload = "\n".join(str(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _flags(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in ("pasted_chars", "left_seconds", "duration_s"):
        try:
            out[key] = max(0, int(raw.get(key) or 0))
        except (TypeError, ValueError):
            out[key] = 0
    return out


def resolve(payload: dict) -> dict:
    """把请求体解析成批改上下文；非法输入抛 ValueError（路由层转 400）。"""
    payload = payload if isinstance(payload, dict) else {}
    kind = str(payload.get("kind") or "").strip()
    if kind not in KINDS:
        raise ValueError("批改类型必须是 writing / translation / sentence")
    text = str(payload.get("text") or "").strip()
    if len(text) < 10:
        raise ValueError("提交内容太短，至少 10 个字符")
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT]
    flags = _flags(payload.get("flags"))
    prompt_id = str(payload.get("prompt_id") or "").strip()
    if not prompt_id:
        raise ValueError("缺少 prompt_id")
    if kind == "sentence":
        item = content.sentence(prompt_id)
        if item is None:
            raise ValueError("没有这道单句练习题")
        version = _digest(item.get("zh"), item.get("reference"))
        text_prompt = prompts.sentence_review_prompt(item, text)
    else:
        item = content.pack(kind, prompt_id)
        if item is None:
            raise ValueError("没有这道题")
        version = str(item.get("content_version") or "")
        hard = rubric.inspect(kind, text, item, flags)
        text_prompt = (prompts.writing_review_prompt(item, text, hard)
                       if kind == "writing"
                       else prompts.translation_review_prompt(item, text, hard))
    context_hash = _digest(kind, prompt_id, version, text,
                           json.dumps(flags, sort_keys=True))
    return {
        "kind": kind,
        "prompt_id": prompt_id,
        "item": item,
        "text": text,
        "flags": flags,
        "content_version": version,
        "context_hash": context_hash,
        "prompt": text_prompt,
    }


def _generate(prompt: str, cfg, abort: threading.Event) -> tuple[str, str, dict]:
    text = ""
    error = ""
    usage: dict = {}
    request = agent.AgentRequest(prompt, system_override=prompts.SYSTEM,
                                 use_tools=False, mode="quick")
    for event in agent.run(request, cfg=cfg, abort=abort):
        if event.kind == "done":
            text = str(event.data.get("text") or "")
            usage = event.data.get("usage") or {}
        elif event.kind == "error":
            error = event.text
    return text, error, usage


def _usage(raw: dict) -> tuple[int, int]:
    raw = raw if isinstance(raw, dict) else {}
    return (int(raw.get("input_tokens") or raw.get("prompt_tokens") or 0),
            int(raw.get("output_tokens") or raw.get("completion_tokens") or 0))


def _one_sample(info: dict, cfg, abort: threading.Event) -> tuple[dict, dict]:
    """一次模型调用 + 解析 + 校验；JSON 失败带更硬约束重试一次。"""
    text, error, usage = _generate(info["prompt"], cfg, abort)
    if error:
        raise RuntimeError(error)
    if not text.strip():
        raise RuntimeError("模型返回了空内容")
    try:
        obj = parse_object(text)
        return review.validate(info["kind"], obj, info["text"], info["item"],
                               info["flags"]), usage
    except Exception:
        if abort.is_set():
            raise
        retry_text, retry_error, retry_usage = _generate(
            info["prompt"] + STRICT_SUFFIX, cfg, abort)
        if retry_error or not retry_text.strip():
            raise
        obj = parse_object(retry_text)
        return review.validate(info["kind"], obj, info["text"], info["item"],
                               info["flags"]), retry_usage or usage


def run_review(info: dict, cfg, abort: threading.Event,
               samples: int | None = None) -> tuple[dict, dict, int, int]:
    """跑 N 次并校验；返回 (结果, usage, 成功次数, 失败次数)。"""
    count = samples or SAMPLE_COUNT[info["kind"]]
    rows: list[dict] = []
    failed = 0
    last_error: Exception | None = None
    usage_in = usage_out = 0
    for _ in range(max(1, count)):
        if abort.is_set():
            break
        try:
            row, usage = _one_sample(info, cfg, abort)
        except Exception as exc:
            diagnostics.log_swallow("训练批改：单次评分失败", exc)
            last_error = exc
            failed += 1
            continue
        rows.append(row)
        tokens_in, tokens_out = _usage(usage)
        usage_in += tokens_in
        usage_out += tokens_out
    if not rows:
        detail = str(last_error or "")[:200]
        raise RuntimeError(
            f"模型没有返回可用的批改结果：{detail}" if detail
            else "模型没有返回可用的批改结果，请重试")
    if info["kind"] == "sentence":
        result = rows[0]
    else:
        result = review.merge_reviews(rows, info["kind"])
    result["prompt_version"] = PROMPT_VERSION
    result["content_version"] = info["content_version"]
    result["samples_ok"] = len(rows)
    result["samples_failed"] = failed
    return (result, {"input_tokens": usage_in, "output_tokens": usage_out},
            len(rows), failed)


def _ensure_worker() -> None:
    global _WORKER, _RECOVERED
    if not _RECOVERED:
        _RECOVERED = True
        try:
            conn = store.connect()
            try:
                for kind in KINDS.values():
                    results.recover_orphans(conn, kind=kind)
            finally:
                conn.close()
        except Exception as exc:
            diagnostics.log_swallow("训练批改：恢复孤儿任务", exc)
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="train-review",
                                       daemon=True)
            _WORKER.start()


def _worker_loop() -> None:
    while True:
        result_id, payload = _QUEUE.get()
        try:
            run_job(result_id, payload)
        except Exception as exc:
            diagnostics.log_swallow("训练批改：worker 单条任务", exc)
        finally:
            _QUEUE.task_done()


def submit(payload: dict, *, target_id: str = "", force: bool = False) -> dict:
    info = resolve(payload)
    cfg, model = _review_cfg()
    _ensure_worker()
    key = dict(kind=KINDS[info["kind"]], target_type=info["kind"],
               target_id=target_id or info["prompt_id"], scope="train",
               context_hash=info["context_hash"], prompt_version=PROMPT_VERSION)
    conn = store.connect()
    try:
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
                results.mark_superseded(conn, **key)
        else:
            results.mark_superseded(conn, **key)
        saved = {
            "kind": info["kind"], "prompt_id": info["prompt_id"],
            "text": info["text"], "flags": info["flags"],
            "content_version": info["content_version"],
            "mode": str(payload.get("mode") or "practice"),
        }
        result_id, created = results.create(
            conn, **key, model=model,
            input_json=json.dumps(saved, ensure_ascii=False))
        if not created:
            row = results.get(conn, result_id)
            return {"id": result_id,
                    "status": (row or {}).get("status", "pending"),
                    "cached": True}
    finally:
        conn.close()
    _QUEUE.put((result_id, saved))
    return {"id": result_id, "status": "pending", "cached": False}


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


def run_job(result_id: int, payload: dict) -> None:
    conn = store.connect()
    try:
        if not results.claim(conn, result_id):
            return
        results.update(conn, result_id, error="")
        info = resolve(payload)
        cfg, model = _review_cfg()
        run_id = observability.start_run(
            surface="train", kind=KINDS[info["kind"]], model=model,
            result_id=result_id, meta={"prompt_id": info["prompt_id"],
                                       "chars": len(info["text"])}, conn=conn)
        started = time.monotonic()
        abort = threading.Event()
        timed_out = {"value": False}

        def on_timeout() -> None:
            timed_out["value"] = True
            abort.set()

        timer = threading.Timer(TIMEOUT[info["kind"]], on_timeout)
        timer.daemon = True
        with _LOCK:
            _ABORTS[result_id] = abort
        timer.start()
        status, error, content_json, usage = "error", "", None, {}
        try:
            result, usage, ok, failed = run_review(info, cfg, abort)
            if abort.is_set() and not ok:
                status = "error" if timed_out["value"] else "canceled"
                error = "批改超时" if timed_out["value"] else ""
            else:
                status = "done"
                content_json = json.dumps(result, ensure_ascii=False)
                if failed:
                    error = f"有 {failed} 次评分未返回可用结果，已用其余结果合并。"
        except Exception as exc:
            status, error = "error", str(exc)[:500]
        finally:
            timer.cancel()
            with _LOCK:
                _ABORTS.pop(result_id, None)
        current = results.get(conn, result_id)
        if current and current["status"] == "canceled":
            status, error = "canceled", ""
        ms = int((time.monotonic() - started) * 1000)
        tokens_in, tokens_out = _usage(usage)
        results.update(
            conn, result_id, status=status, error=error, model=model, ms=ms,
            tokens_in=tokens_in, tokens_out=tokens_out,
            content_json=content_json or "")
        observability.finish_run(
            run_id, status=status, ms=ms, tokens_in=tokens_in,
            tokens_out=tokens_out, error=error, conn=conn)
    finally:
        conn.close()


def review_sync(payload: dict, *, samples: int | None = None) -> dict:
    """同步批改：单句审核（目标 2 秒）与 `tools/train_eval.py` 共用。"""
    info = resolve(payload)
    cfg, model = _review_cfg()
    abort = threading.Event()
    timer = threading.Timer(TIMEOUT[info["kind"]], abort.set)
    timer.daemon = True
    timer.start()
    started = time.monotonic()
    try:
        result, usage, ok, failed = run_review(info, cfg, abort, samples)
    finally:
        timer.cancel()
    if abort.is_set() and not ok:
        raise RuntimeError("批改超时")
    return {
        "review": result,
        "model": model,
        "samples_ok": ok,
        "samples_failed": failed,
        "usage": usage,
        "ms": int((time.monotonic() - started) * 1000),
    }


def wait_result(result_id: int, timeout: float = 10.0) -> dict | None:
    """测试/脚本用：等任务离开 pending/running。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conn = store.connect()
        try:
            row = results.get(conn, result_id)
        finally:
            conn.close()
        if row and row["status"] not in ("pending", "running"):
            return row
        time.sleep(0.05)
    return None
