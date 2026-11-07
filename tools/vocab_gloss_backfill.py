"""给历史生词补中文词义：把「为什么错」降为错因备注。

背景：2.56.1 自动入本时 `meaning` 存的是模型 `why`（如
「搭配错：different 不直接与 variety 搭配」），不是中文词义。
2.58.1 起批改会多回 `gloss`，新词直接存「词义｜错因」；
本工具用一次批量模型调用给历史条目补词义，旧释义原样保留在 `｜` 后面。

只处理 `source` 为 sentence / translation / daily、且现有释义看起来像解释
（首个 `｜` 段超过 12 字，或含 拼写/语法/搭配/误译/漏译/标点/结构/应为/→/错/多余/指）
的条目；`manual` 条目不动，已经像词义的条目不动。

默认只读；`--apply` 才写库。
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import agent, config, store  # noqa: E402
from learnsys.core.jsontext import parse_object  # noqa: E402
from learnsys.llm.config import load_config  # noqa: E402

SOURCES = ("sentence", "translation", "daily")
BATCH = 20
TIMEOUT = 90
# 看起来像“为什么错”的释义标记；首个 ｜ 段短且不含这些词，视为已有词义。
_MARKERS = re.compile(
    r"拼写|语法|搭配|误译|漏译|标点|结构|应为|→|错|多余|指")
SYSTEM = "你是六级词汇助手。只输出一个合法 JSON 对象，不输出 Markdown 或解释。"

PROMPT = """下面是生词本里的英文词条。请给每个词条写 2–12 字的中文词义，
只写词义，不要写语法解释。现有释义可能是一句解释，只用来判断词义。

只输出 JSON：{{"词条":"中文词义"}}；不确定的写空字符串，不要编造。
不要输出 Markdown 或额外解释。

{lines}
"""


def needs_gloss(meaning: str) -> bool:
    meaning = str(meaning or "").strip()
    if not meaning:
        return True
    first = meaning.split("｜", 1)[0].strip()
    if len(first) <= 12 and not _MARKERS.search(first):
        return False
    return bool(_MARKERS.search(meaning)) or len(first) > 12


def collect(conn) -> dict:
    items = store.list_vocab(conn, limit=500, status="active")["items"]
    rows = [item for item in items
            if str(item.get("source") or "") in SOURCES
            and needs_gloss(item.get("meaning") or "")]
    return {"items": items, "rows": rows}


def _prompt_for(rows: list[dict]) -> str:
    lines = []
    for index, item in enumerate(rows, start=1):
        context = " ".join(str(item.get("context") or "").split())[:80]
        lines.append(f"{index}. {item['word']} ｜ 现有释义：{item.get('meaning') or '无'}"
                     + (f" ｜ 上下文：{context}" if context else ""))
    return PROMPT.format(lines="\n".join(lines))


def _run(prompt: str) -> tuple[dict, str]:
    cfg = dataclasses.replace(load_config(), max_tokens=2000)
    abort = threading.Event()
    timer = threading.Timer(TIMEOUT, abort.set)
    timer.daemon = True
    timer.start()
    try:
        text, error, _usage = agent.complete(
            prompt, system_override=SYSTEM, cfg=cfg, abort=abort, mode="quick")
    finally:
        timer.cancel()
    if abort.is_set() and not text.strip():
        return {}, "模型调用超时"
    if error:
        return {}, error
    data = parse_object(text)
    if not isinstance(data, dict):
        return {}, "模型没有返回 JSON 对象"
    return {str(key).strip().lower(): str(value or "").strip()
            for key, value in data.items()}, ""


def propose(rows: list[dict]) -> dict:
    proposals, errors, skipped = [], [], []
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        data, error = _run(_prompt_for(chunk))
        if error:
            errors.append(f"第 {start // BATCH + 1} 批：{error}")
            continue
        for item in chunk:
            gloss = data.get(str(item["word"]).strip().lower(), "")
            old = str(item.get("meaning") or "").strip()
            if (not gloss or not re.search(r"[一-鿿]", gloss)
                    or len(gloss) > 30):
                skipped.append({"word": item["word"], "reason": "模型没给出有效词义"})
                continue
            new = gloss if not old or old.startswith(gloss) else f"{gloss}｜{old}"
            proposals.append({"id": item["id"], "word": item["word"],
                              "old": old, "gloss": gloss, "new": new})
    return {"proposals": proposals, "errors": errors, "skipped": skipped}


def apply(conn, report: dict) -> dict:
    updated = 0
    for row in report["proposals"]:
        store.update_vocab(conn, row["id"], meaning=row["new"])
        updated += 1
    return {"updated": updated}


def render(report: dict, proposals: dict, applied: dict | None = None) -> str:
    lines = ["历史生词补词义（只读）" if applied is None
             else "历史生词补词义（已执行）",
             f"活动生词 {len(report['items'])} 条；需要补词义 {len(report['rows'])} 条；"
             f"本次给出 {len(proposals['proposals'])} 条"]
    for row in proposals["proposals"]:
        lines.append(f"  #{row['id']}  {row['word']}  →  {row['new']}")
    for row in proposals["skipped"]:
        lines.append(f"  [跳过] {row['word']}：{row['reason']}")
    for error in proposals["errors"]:
        lines.append(f"  [错误] {error}")
    if applied is not None:
        lines.append(f"执行结果：更新 {applied['updated']} 条")
    else:
        lines.append("预检：加 --apply 才会写库。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="历史生词补中文词义（只读默认）")
    parser.add_argument("--db", default=str(config.db_path()))
    parser.add_argument("--apply", action="store_true", help="真正写库")
    args = parser.parse_args(argv)
    conn = store.connect(pathlib.Path(args.db))
    try:
        report = collect(conn)
        proposals = propose(report["rows"]) if report["rows"] else {
            "proposals": [], "errors": [], "skipped": []}
        applied = apply(conn, proposals) if args.apply else None
        print(render(report, proposals, applied))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
