"""六级分析任务：后台队列 + 结果资产 + 状态机。

旧接口 `/analyze` 仍然同步跑（file:// 工作台要用），但 HTTP 页面改走
`POST /api/cet6/analysis` + 轮询，关掉面板/刷新页面都不会丢结果。
"""
from __future__ import annotations

import dataclasses
import json
import queue
import re
import threading
import time

from learnsys import agent, store
from learnsys.agent.config import load_config
from learnsys.services import observability, results

ANALYSIS_KIND = "cet6_analyze"
PROMPT_VERSION = "cet6-analyze-v1"
ANALYSIS_TIMEOUT = 180.0

SYSTEM = "你是严谨、具体的英语听力教练。你只输出 JSON，不输出解释或 Markdown。"

PROMPT_HEAD = """下面是一个学生在某段英语听力里的断点记录。
每条包含：句子编号、他勾选的断点标签（生词/听不出/连读/句法/走神）、他自己写的原因、英文原句、循环回绕次数和总播放次数。
「循环回绕」是他主动把这一句反复回绕播放的次数，是难度信号：回绕多的句子通常更难；没有勾标签但反复循环的句子也要特别留意。不要只凭次数下结论，要结合标签和原话。
请做个性化分析，不要泛泛而谈：
1. summary：2–3 句话概括他当前最主要的听力障碍。
2. patterns：2–3 个问题模式；每个包含 name、evidence（引用他的原话、标签或循环次数）、advice（具体练法）。
3. priority：最该优先回听的 2–3 句；包含 sentence（句子编号）和 reason。
4. plan：3 条本周可执行的练习计划，每条不超过 2 句。
只输出 JSON：
{"summary":"...","patterns":[{"name":"...","evidence":"...","advice":"..."}],"priority":[{"sentence":3,"reason":"..."}],"plan":["...","..."]}

学生记录：
"""

PROMPT_PAPER = """下面是一个学生在**整卷**英语听力里记录的全部断点（跨 Section A/B/C）。
每条包含：所属 Section / 题型、句子编号、勾选的断点标签（生词/听不出/连读/句法/走神）、他自己写的原因、英文原句、循环回绕次数和总播放次数。
「循环回绕」是他主动把这一句反复回绕播放的次数，是难度信号：回绕多的句子通常更难；没有勾标签但反复循环的句子也要特别留意。不要只凭次数下结论，要结合标签和原话。
请做整卷级分析，按题型对比，不要泛泛而谈：
1. summary：3 句话概括他整卷最主要的听力障碍，并指出最弱的题型。
2. patterns：2–4 个跨段落反复出现的模式；每个包含 name、evidence（引用他的原话、标签或循环次数）、advice（具体练法）。
3. priority：最该优先回听的 3–5 句；包含 sentence（句子编号）和 reason。
4. plan：3 条本周可执行的练习计划，每条不超过 2 句。
只输出 JSON：
{"summary":"...","patterns":[{"name":"...","evidence":"...","advice":"..."}],"priority":[{"sentence":3,"reason":"..."}],"plan":["...","..."]}

学生记录：
"""

_QUEUE: "queue.Queue[tuple[int, dict]]" = queue.Queue()
_WORKER: threading.Thread | None = None
_ABORTS: dict[int, threading.Event] = {}
_LOCK = threading.Lock()
_RECOVERED = False


def target_id(paper_id: str, section: str, item: str, scope: str) -> str:
    if scope == "paper":
        return str(paper_id or "")
    return "|".join(str(x or "") for x in (paper_id, section, item))


def normalize_record(raw: dict) -> dict:
    """按句号排序、去重、限 120 条；非法的句子直接丢。"""
    rows: list[dict] = []
    seen: set[int] = set()
    for item in (raw.get("sentences") or []):
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("sentence"))
        except (TypeError, ValueError):
            continue
        if number in seen:
            continue
        seen.add(number)
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [x for x in re.split(r"[、,，\s]+", tags) if x]
        tags = [str(x).strip()[:20] for x in tags if str(x).strip()][:8]
        try:
            loops = max(0, int(item.get("loops") or 0))
            plays = max(0, int(item.get("plays") or 0))
        except (TypeError, ValueError):
            loops = plays = 0
        rows.append({
            "sentence": number,
            "en": str(item.get("en") or "")[:2000],
            "tags": tags,
            "note": str(item.get("note") or "")[:500],
            "loops": loops,
            "plays": plays,
            "section": str(item.get("section") or "")[:100],
            "item": str(item.get("item") or "")[:100],
        })
    rows.sort(key=lambda row: row["sentence"])
    scope = raw.get("scope") if raw.get("scope") in ("item", "paper") else "item"
    return {
        "paper_id": str(raw.get("paper_id") or "")[:300],
        "paper": str(raw.get("paper") or "")[:300],
        "section": str(raw.get("section") or "")[:200],
        "item": str(raw.get("item") or "")[:200],
        "scope": scope,
        "sentences": rows[:120],
    }


def context_hash(record: dict) -> str:
    import hashlib
    payload = json.dumps(
        {key: record.get(key) for key in
         ("paper_id", "paper", "section", "item", "scope", "sentences")},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def build_prompt(record: dict) -> str:
    head = PROMPT_PAPER if record.get("scope") == "paper" else PROMPT_HEAD
    lines = []
    for row in record.get("sentences") or []:
        tags = "、".join(row.get("tags") or []) or "无"
        note = (row.get("note") or "").strip() or "无"
        where = ""
        if row.get("section") or row.get("item"):
            where = f"{row.get('section', '')} / {row.get('item', '')} · "
        lines.append(
            f"{where}第 {row.get('sentence')} 句 | 标签：{tags} | "
            f"循环回绕：{row.get('loops', 0)} 次（共播放 {row.get('plays', 0)} 次） | "
            f"我的原因：{note} | 英文：{row.get('en', '')}")
    return (head + f"\n材料：{record.get('paper', '')} / {record.get('section', '')} / "
            f"{record.get('item', '')}\n" + "\n".join(lines) + "\n\n只输出 JSON。")


def _repair_json_text(text: str) -> str:
    """修复 flash 常见的两类坏 JSON：字符串里未转义的引号、未转义的换行。"""
    out: list[str] = []
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\":
            out.append(char)
            escaped = True
            continue
        if char == '"':
            if not in_string:
                in_string = True
                out.append(char)
                continue
            # 字符串里的引号只有在后面跟着 , : } ] 或结束时才是收尾
            cursor = index + 1
            while cursor < len(text) and text[cursor] in " \t\r\n":
                cursor += 1
            following = text[cursor] if cursor < len(text) else ""
            if following in (",", ":", "}", "]", ""):
                in_string = False
                out.append(char)
            else:
                out.append('\\"')
            continue
        if in_string and char in "\r\n":
            out.append("\\n")
            continue
        out.append(char)
    return "".join(out)


def parse_json_text(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    i, j = text.find("{"), text.rfind("}")
    candidates = [text]
    if i >= 0 and j > i:
        candidates.append(text[i:j + 1])
    candidates.append(_repair_json_text(candidates[-1]))
    candidates.append(re.sub(r",\s*([}\]])", r"\1", candidates[-1]))
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate, strict=False)
        except Exception as exc:
            last_error = exc
    raise ValueError(f"模型输出里没有可解析的 JSON：{last_error}")


def validate_analysis(obj: dict) -> dict:
    """缺字段补空、错类型丢掉；保证前端拿到稳定形状。"""
    obj = obj if isinstance(obj, dict) else {}
    patterns = []
    for item in (obj.get("patterns") or [])[:5]:
        if isinstance(item, dict):
            patterns.append({
                "name": str(item.get("name") or ""),
                "evidence": str(item.get("evidence") or ""),
                "advice": str(item.get("advice") or ""),
            })
    priority = []
    for item in (obj.get("priority") or [])[:8]:
        if isinstance(item, dict):
            try:
                sentence = int(item.get("sentence"))
            except (TypeError, ValueError):
                continue
            priority.append({"sentence": sentence,
                             "reason": str(item.get("reason") or "")})
    plan = [str(x) for x in (obj.get("plan") or []) if str(x).strip()][:6]
    return {"summary": str(obj.get("summary") or ""), "patterns": patterns,
            "priority": priority, "plan": plan}


def _analysis_cfg():
    """分析固定用快模型（deepseek-flash）；pro 留给需要深度推理的问答。"""
    cfg = load_config()
    return dataclasses.replace(cfg, model=cfg.fast_model or cfg.model)


def _usage(usage: dict) -> tuple[int, int]:
    usage = usage if isinstance(usage, dict) else {}
    return (int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            int(usage.get("output_tokens") or usage.get("completion_tokens") or 0))


def _generate(prompt: str, cfg, abort: threading.Event) -> tuple[str, str, dict]:
    text = ""
    error = ""
    usage: dict = {}
    request = agent.AgentRequest(
        prompt, system_override=SYSTEM, use_tools=False, mode="quick")
    for event in agent.run(request, cfg=cfg, abort=abort):
        if event.kind == "done":
            text = str(event.data.get("text") or "")
            usage = event.data.get("usage") or {}
        elif event.kind == "error":
            error = event.text
    return text, error, usage


def _ensure_worker() -> None:
    """第一次提交时启动；顺便清理上次进程遗留的 pending/running。"""
    global _WORKER, _RECOVERED
    if not _RECOVERED:
        _RECOVERED = True
        try:
            conn = store.connect()
            try:
                results.recover_orphans(conn)
            finally:
                conn.close()
        except Exception:
            pass
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(
                target=_worker_loop, name="cet6-analysis", daemon=True)
            _WORKER.start()


def _worker_loop() -> None:
    while True:
        result_id, record = _QUEUE.get()
        try:
            run_job(result_id, record)
        except Exception:
            # 单条任务失败不能带走整个 worker；行状态由 run_job 尽量写好
            pass
        finally:
            _QUEUE.task_done()


def submit(raw: dict, *, force: bool = False) -> dict:
    record = normalize_record(raw)
    if not record["sentences"]:
        raise ValueError("没有可分析的记录")
    scope = record["scope"]
    kind = ANALYSIS_KIND
    target_type = "paper" if scope == "paper" else "item"
    tid = target_id(record["paper_id"], record["section"], record["item"], scope)
    digest = context_hash(record)
    cfg = _analysis_cfg()
    # 先起 worker / 清理上次进程遗留，再建本次的 pending 行；
    # 反过来会把刚建的行当成「重启孤儿」直接标错。
    _ensure_worker()
    conn = store.connect()
    try:
        if not force:
            done = results.find_done(
                conn, kind=kind, target_type=target_type, target_id=tid,
                scope=scope, context_hash=digest, prompt_version=PROMPT_VERSION)
            if done:
                results.update(conn, done["id"], cache_hit=1)
                run_id = observability.start_run(
                    surface="cet6", kind=kind,
                    model=done.get("model") or cfg.model,
                    result_id=done["id"], meta={"cache_hit": True})
                observability.finish_run(run_id, status="done", ms=0, cache_hit=1)
                return {"id": done["id"], "status": "done", "cached": True}
            active = results.find_by_key(
                conn, kind=kind, target_type=target_type, target_id=tid,
                scope=scope, context_hash=digest, prompt_version=PROMPT_VERSION)
            if active and active["status"] in ("pending", "running"):
                return {"id": active["id"], "status": active["status"], "cached": True}
        else:
            results.mark_superseded(
                conn, kind=kind, target_type=target_type, target_id=tid,
                scope=scope, context_hash=digest, prompt_version=PROMPT_VERSION)
        result_id, created = results.create(
            conn, kind=kind, target_type=target_type, target_id=tid, scope=scope,
            context_hash=digest, prompt_version=PROMPT_VERSION, model=cfg.model,
            input_json=json.dumps(record, ensure_ascii=False))
        if not created:
            row = results.get(conn, result_id)
            return {"id": result_id, "status": (row or {}).get("status", "pending"),
                    "cached": True}
    finally:
        conn.close()
    _ensure_worker()
    _QUEUE.put((result_id, record))
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


def run_job(result_id: int, record: dict) -> None:
    conn = store.connect()
    try:
        if not results.claim(conn, result_id):
            return
        results.update(conn, result_id, error="")
        cfg = _analysis_cfg()
        run_id = observability.start_run(
            surface="cet6", kind=ANALYSIS_KIND, model=cfg.model,
            result_id=result_id, meta={"scope": record.get("scope", "item")})
        started = time.monotonic()
        abort = threading.Event()
        timed_out = {"value": False}

        def on_timeout() -> None:
            timed_out["value"] = True
            abort.set()

        timer = threading.Timer(ANALYSIS_TIMEOUT, on_timeout)
        timer.daemon = True
        with _LOCK:
            _ABORTS[result_id] = abort
        timer.start()
        status, error, content, usage = "error", "", None, {}
        try:
            text, error, usage = _generate(build_prompt(record), cfg, abort)
            if abort.is_set() and not text.strip():
                if timed_out["value"]:
                    status, error = "error", "分析超时"
                else:
                    status, error = "canceled", ""
            elif error:
                status = "error"
            else:
                try:
                    content = validate_analysis(parse_json_text(text))
                except Exception:
                    # flash 偶尔在中文引号/换行上失手：带着更硬的 JSON 约束再要一次
                    if abort.is_set():
                        raise
                    retry_prompt = build_prompt(record) + (
                        "\n\n注意：只输出一个合法 JSON 对象；字符串内部的双引号必须"
                        "转义成 \\\"，不要输出 Markdown 代码块。")
                    retry_text, retry_error, retry_usage = _generate(
                        retry_prompt, cfg, abort)
                    if retry_error or not retry_text.strip():
                        raise
                    text = retry_text
                    usage = retry_usage or usage
                    content = validate_analysis(parse_json_text(text))
                status = "done"
        except Exception as exc:
            message = str(exc)
            if "JSON" in message:
                error = "模型输出不是合法 JSON，自动重试后仍失败；再点一次「重试」即可。"
            else:
                error = message[:500]
            status = "error"
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
            conn, result_id, status=status, error=error,
            content_json=json.dumps(content, ensure_ascii=False) if content else "",
            model=cfg.model, ms=ms, tokens_in=tokens_in, tokens_out=tokens_out)
        observability.finish_run(
            run_id, status=status, ms=ms, tokens_in=tokens_in,
            tokens_out=tokens_out, error=error)
    finally:
        conn.close()


def analyze_sync(raw: dict) -> dict:
    """旧 `/analyze` 的同步实现：file:// 工作台仍走这里。"""
    record = normalize_record(raw)
    if not record["sentences"]:
        raise ValueError("没有可分析的记录")
    cfg = _analysis_cfg()
    abort = threading.Event()
    timer = threading.Timer(ANALYSIS_TIMEOUT, abort.set)
    timer.daemon = True
    timer.start()
    try:
        text, error, _ = _generate(build_prompt(record), cfg, abort)
    finally:
        timer.cancel()
    if abort.is_set() and not text.strip():
        raise RuntimeError("分析超时")
    if error:
        raise RuntimeError(error)
    return {"analysis": validate_analysis(parse_json_text(text)),
            "model": cfg.model}


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
