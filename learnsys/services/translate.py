"""翻译服务：划词查词 + 逐句译文，结果写进 `service_results` 缓存。

先用快模型（`fast_model`，默认 deepseek-flash）；同一句话第二次打开不再花钱。
失败不抛 500，返回 `{"translation": "", "error": "翻译服务暂时不可用"}` 让界面
显示一句人话，不把工作台拖死。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
import time

from learnsys import agent, store
from learnsys.llm.config import load_config
from learnsys.services import analysis, observability, results

TRANSLATE_KIND = "translate"
PROMPT_VERSION = "translate-v1"
TRANSLATE_TIMEOUT = 60.0

SYSTEM = "你是英语学习助手。只输出 JSON，不输出解释或 Markdown。"

WORD_PROMPT = """请翻译下面的英语单词或短语，并结合上下文判断它在句中的意思。
只输出 JSON：{{"translation":"中文翻译","meaning":"一句话释义","phonetic":"音标"}}
不确定的字段留空字符串，不要编造音标。

原文：{text}
上下文：{context}
"""

SENTENCE_PROMPT = """请把下面的英语句子/短段落翻译成自然、准确的中文。
只输出 JSON：{{"translation":"中文译文"}}

原文：
{text}
"""

BATCH_PROMPT = """下面是一段英语听力原文的逐句列表。请逐句翻译成中文。
只输出 JSON，键是句子编号（字符串），值是中文译文；不要漏句，不要合并句子。

{sentences}
"""


def _hash(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]


def _fast_cfg(cfg, max_tokens: int = 600):
    return dataclasses.replace(
        cfg, model=cfg.model_for("translate") or cfg.fast_model or cfg.model,
        max_tokens=max_tokens)


def _run_text(prompt: str, cfg, max_tokens: int = 600) -> tuple[str, str, dict]:
    abort = threading.Event()
    timer = threading.Timer(TRANSLATE_TIMEOUT, abort.set)
    timer.daemon = True
    timer.start()
    text, error, usage = "", "", {}
    try:
        request = agent.AgentRequest(
            prompt, system_override=SYSTEM, use_tools=False, mode="quick")
        for event in agent.run(request, cfg=_fast_cfg(cfg, max_tokens), abort=abort):
            if event.kind == "done":
                text = str(event.data.get("text") or "")
                usage = event.data.get("usage") or {}
            elif event.kind == "error":
                error = event.text
    finally:
        timer.cancel()
    if abort.is_set() and not text.strip():
        error = "翻译超时"
    return text, error, usage


def _cache_key(text: str, kind: str, context: dict | None) -> tuple[str, str]:
    context = context if isinstance(context, dict) else {}
    if kind == "word":
        return _hash(text.strip().lower()), _hash(str(context.get("sentence") or ""))
    scope = "|".join(str(context.get(key) or "") for key in
                     ("paper_id", "section", "item"))
    return _hash(text.strip()), _hash(scope)


def _parse(text: str) -> dict:
    return analysis.parse_json_text(text)


def _save(conn, *, text: str, kind: str, target_id: str, scope: str,
          payload: dict, model: str, ms: int, tokens_in: int = 0,
          tokens_out: int = 0) -> int:
    result_id, _ = results.create(
        conn, kind=TRANSLATE_KIND, target_type=kind, target_id=target_id,
        scope=scope, context_hash="", prompt_version=PROMPT_VERSION,
        model=model, input_json=json.dumps({"text": text}, ensure_ascii=False))
    results.update(
        conn, result_id, status="done", error="", model=model, ms=ms,
        tokens_in=tokens_in, tokens_out=tokens_out,
        content_json=json.dumps(payload, ensure_ascii=False))
    return result_id


def _cached(conn, *, kind: str, target_id: str, scope: str) -> dict | None:
    row = results.find_done(
        conn, kind=TRANSLATE_KIND, target_type=kind, target_id=target_id,
        scope=scope, context_hash="", prompt_version=PROMPT_VERSION)
    if not row:
        return None
    try:
        content = json.loads(row.get("content_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(content, dict):
        return None
    content["_result_id"] = row.get("id") or 0
    return content


def translate(text: str, *, kind: str = "word", context: dict | None = None) -> dict:
    text = str(text or "").strip()[:1000]
    if not text:
        return {"translation": "", "error": "没有可翻译的文本"}
    kind = kind if kind in ("word", "sentence", "paragraph") else "word"
    target_id, scope = _cache_key(text, kind, context)
    conn = store.connect()
    try:
        # 本地优先：自己生词本里已经有释义的词，不再花一次模型调用。
        if kind == "word":
            row = conn.execute(
                "SELECT id, meaning, phonetic FROM vocab_items "
                "WHERE normalized = ? AND status = 'active'",
                (text.strip().lower(),)).fetchone()
            if row is not None and str(row[1] or "").strip():
                meaning = str(row[1]).strip()
                return {"translation": meaning, "meaning": meaning,
                        "phonetic": str(row[2] or ""), "cached": True,
                        "source": "vocab", "vocab_id": int(row[0]),
                        "result_id": 0}
        cached = _cached(conn, kind=kind, target_id=target_id, scope=scope)
        if cached:
            out = dict(cached)
            result_id = int(out.pop("_result_id", 0) or 0)
            if result_id:
                results.update(conn, result_id, cache_hit=1)
                cached_cfg = load_config()
                run_id = observability.start_run(
                    surface="cet6", kind="translate",
                    model=cached_cfg.fast_model or cached_cfg.model,
                    result_id=result_id,
                    meta={"type": kind, "cache_hit": True})
                observability.finish_run(
                    run_id, status="done", ms=0, cache_hit=1)
            out.update({"cached": True, "result_id": result_id})
            return out
    finally:
        conn.close()

    cfg = load_config()
    context_text = ""
    if isinstance(context, dict):
        context_text = str(context.get("sentence") or "")[:600]
    if kind == "word":
        prompt = WORD_PROMPT.format(text=text, context=context_text or "（无）")
    else:
        prompt = SENTENCE_PROMPT.format(text=text)
    started = time.monotonic()
    raw, error, usage = _run_text(prompt, cfg, 600 if kind == "word" else 1200)
    ms = int((time.monotonic() - started) * 1000)
    if error or not raw.strip():
        return {"translation": "", "error": "翻译服务暂时不可用",
                "detail": (error or "模型没有返回文本")[:200]}
    try:
        obj = _parse(raw)
    except Exception as exc:
        return {"translation": "", "error": "翻译结果解析失败",
                "detail": str(exc)[:200]}
    payload = {"translation": str(obj.get("translation") or "")}
    if kind == "word":
        payload["meaning"] = str(obj.get("meaning") or "")
        payload["phonetic"] = str(obj.get("phonetic") or "")
    if not payload["translation"]:
        return {"translation": "", "error": "翻译服务暂时不可用"}
    tokens_in = int(usage.get("input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    run_id = observability.start_run(
        surface="cet6", kind="translate", model=cfg.fast_model or cfg.model,
        meta={"type": kind})
    conn = store.connect()
    try:
        result_id = _save(
            conn, text=text, kind=kind, target_id=target_id, scope=scope,
            payload=payload, model=cfg.fast_model or cfg.model, ms=ms,
            tokens_in=tokens_in, tokens_out=tokens_out)
    finally:
        conn.close()
    observability.finish_run(run_id, status="done", ms=ms,
                             tokens_in=tokens_in, tokens_out=tokens_out)
    payload.update({"cached": False, "result_id": result_id})
    return payload


def translate_sentences(sentences: list[dict], *, paper_id: str = "",
                        section: str = "", item: str = "") -> dict:
    """一次翻译一段的所有句子；先查缓存，未命中的一次批量请求。"""
    pairs: dict[int, str] = {}
    for row in sentences or []:
        if not isinstance(row, dict):
            continue
        try:
            number = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        text = str(row.get("en") or "").strip()
        if text:
            pairs[number] = text[:1000]
    if not pairs:
        return {"items": {}, "cached": 0}

    context = {"paper_id": paper_id, "section": section, "item": item}
    out: dict[str, dict] = {}
    cached_n = 0
    missing: dict[int, str] = {}
    conn = store.connect()
    try:
        for number, text in pairs.items():
            target_id, scope = _cache_key(text, "sentence", context)
            cached = _cached(conn, kind="sentence", target_id=target_id, scope=scope)
            if cached:
                out[str(number)] = {"translation": cached.get("translation", "")}
                cached_n += 1
            else:
                missing[number] = text
    finally:
        conn.close()

    cfg = load_config()
    # 一次 12 句：实测 23 句会撞上 600 token 上限、JSON 被截断；
    # 分块后每块几百 token，既稳又不会明显变慢。
    for chunk_start in range(0, len(missing), 12):
        chunk = dict(list(missing.items())[chunk_start:chunk_start + 12])
        lines = "\n".join(f"{number}. {text}" for number, text in chunk.items())
        started = time.monotonic()
        raw, error, usage = _run_text(
            BATCH_PROMPT.format(sentences=lines), cfg, 2000)
        ms = int((time.monotonic() - started) * 1000)
        parsed: dict = {}
        if raw.strip() and not error:
            try:
                parsed = _parse(raw)
            except Exception:
                parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        tokens_in = int(usage.get("input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)
        run_id = observability.start_run(
            surface="cet6", kind="translate", model=cfg.fast_model or cfg.model,
            meta={"type": "sentence_batch", "count": len(chunk)})
        conn = store.connect()
        try:
            for number, text in chunk.items():
                translation = str(parsed.get(str(number)) or parsed.get(number) or "")
                if not translation:
                    continue
                target_id, scope = _cache_key(text, "sentence", context)
                _save(conn, text=text, kind="sentence", target_id=target_id,
                      scope=scope, payload={"translation": translation},
                      model=cfg.fast_model or cfg.model, ms=ms,
                      tokens_in=tokens_in, tokens_out=tokens_out)
                out[str(number)] = {"translation": translation}
        finally:
            conn.close()
        observability.finish_run(run_id, status="done", ms=ms,
                                 tokens_in=tokens_in, tokens_out=tokens_out)

    # 批量失败时最多逐句降级 8 句，避免一个坏请求把整段拖成几十次模型调用
    for number, text in list(missing.items())[:8]:
        if str(number) in out:
            continue
        single = translate(text, kind="sentence", context=context)
        if single.get("translation"):
            out[str(number)] = {"translation": single["translation"]}
        else:
            out[str(number)] = {"translation": "",
                                "error": single.get("error", "翻译失败")}
    for number in missing:
        out.setdefault(str(number), {"translation": "", "error": "翻译服务暂时不可用"})
    return {"items": out, "cached": cached_n}
