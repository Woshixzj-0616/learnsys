"""从开源六级题库提取听力选项与答案，生成工作台可读的 quiz.js。

题库来源：ShepiTT/CET_practice_questions（Apache-2.0）的 SQLite。
本地试卷 data.js 只有题干，没有 A-D 选项；这里按「本地听力原文 vs
题库 transcript」的 token 重合度给每份卷选题库套数，再按题号挂选项/答案。

不信任卷名序号：2019-12 卷一实际对应题库 set2；2020-09 三套 transcript
相同，按标题后缀/默认 set1 决胜。匹配结果与分数写进报告，可人工抽查。

用法：
    python tools/cet6_quiz_build.py --db <cet4_v2.db>            # 只读预演
    python tools/cet6_quiz_build.py --db <...> --apply --sidecars # 写 JSON + quiz.js
    python tools/cet6_quiz_build.py --apply --sidecars            # 用现有 JSON 重建 quiz.js
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config  # noqa: E402

CONTENT = ROOT / "learnsys" / "train" / "content" / "cet6_listening_quiz.json"
SOURCE = {
    "name": "ShepiTT/CET_practice_questions",
    "license": "Apache-2.0",
    "url": "https://github.com/ShepiTT/CET_practice_questions",
}
SCHEMA = 1
MIN_PAPER_SCORE = 0.60
TIE_WINDOW = 0.03
MIN_ITEM_SCORE = 0.55
_NON_WORD = re.compile(r"[^0-9a-z一-鿿]+")
_SUFFIX = re.compile(r"（(?:卷|第)([一二三1-3])")
_EXPL_CUT = re.compile(
    r"(Questions\s+\d+\s+to\s+\d+|第\s*\d+\s*页[，,]\s*共\s*\d+\s*页)")


def _clean_explanation(text: str) -> str:
    """解析后面常粘着下一段原文/页码，截到下一个题组提示为止。"""
    value = str(text or "")
    match = _EXPL_CUT.search(value)
    if match:
        value = value[:match.start()]
    return value.strip()[:1200]


def _norm(text: str) -> str:
    return " ".join(_NON_WORD.sub(" ", str(text or "").lower()).split())


def _tokens(text: str) -> set[str]:
    return set(_norm(text).split())


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _suffix_number(title: str) -> int:
    match = _SUFFIX.search(str(title or ""))
    if not match:
        return 1
    value = match.group(1)
    mapping = {"一": 1, "二": 2, "三": 3}
    return mapping[value] if value in mapping else int(value)


def _source_suffix(source_file: str) -> int:
    match = re.search(r"-CET6-(\d)", source_file)
    return int(match.group(1)) if match else 1


def _parse_paper(path: pathlib.Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if "window.PAPER" not in raw:
        return None
    try:
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except ValueError:
        return None
    items = []
    for section in data.get("sections") or []:
        for item in section.get("items") or []:
            questions = [q for q in item.get("question_items") or []
                         if str(q.get("en") or "").strip()]
            items.append({
                "letter": str(section.get("letter") or ""),
                "index": int(item.get("index") or 0),
                "title": str(item.get("title") or ""),
                "transcript": " ".join(
                    str(sentence.get("en") or "")
                    for sentence in item.get("sentences") or []),
                "questions": questions,
            })
    if not any(item["questions"] for item in items):
        return None
    return {"title": path.parent.name, "items": items}


def _load_db(db_path: pathlib.Path) -> dict[str, list[dict]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sources: dict[str, list[dict]] = {}
        groups = conn.execute(
            "SELECT id, source_file, title, transcript FROM question_group "
            "WHERE group_type = 'listening' AND source_file LIKE '%CET6%' "
            "ORDER BY id").fetchall()
        for group in groups:
            questions = {}
            for row in conn.execute(
                    "SELECT id, q_number, correct_answer, explanation FROM question "
                    "WHERE group_id = ? ORDER BY q_number", (group["id"],)):
                options = [
                    {"label": str(opt["label"]), "text": str(opt["text"] or "").strip()}
                    for opt in conn.execute(
                        "SELECT label, text FROM option WHERE question_id = ? "
                        "ORDER BY label", (row["id"],))]
                labels = [opt["label"] for opt in options]
                if (len(options) != 4 or len(set(labels)) != 4
                        or any(not opt["text"] for opt in options)
                        or str(row["correct_answer"] or "").upper() not in labels):
                    continue
                questions[int(row["q_number"])] = {
                    "options": options,
                    "answer": str(row["correct_answer"]).upper(),
                    "explanation": _clean_explanation(row["explanation"]),
                }
            if questions:
                sources.setdefault(group["source_file"], []).append({
                    "title": group["title"] or "",
                    "tokens": _tokens(group["transcript"]),
                    "questions": questions,
                })
        return sources
    finally:
        conn.close()


def _paper_score(paper: dict, groups: list[dict]) -> float:
    totals = []
    for item in paper["items"]:
        tokens = _tokens(item["transcript"])
        if not tokens:
            continue
        totals.append(max((_jaccard(tokens, group["tokens"]) for group in groups),
                          default=0.0))
    return sum(totals) / len(totals) if totals else 0.0


def _match_source(paper: dict, sources: dict[str, list[dict]]):
    ranked = sorted(((_paper_score(paper, groups), source)
                     for source, groups in sources.items()), reverse=True)
    if not ranked or ranked[0][0] < MIN_PAPER_SCORE:
        return None, ranked[:3]
    top_score = ranked[0][0]
    tied = [row for row in ranked if top_score - row[0] <= TIE_WINDOW]
    wanted = _suffix_number(paper["title"])
    tied.sort(key=lambda row: (abs(_source_suffix(row[1]) - wanted),
                               _source_suffix(row[1]), -row[0], row[1]))
    return tied[0][1], tied[:3]


def _map_items(paper: dict, groups: list[dict]) -> dict:
    items = {}
    for item in paper["items"]:
        if not item["questions"]:
            continue
        local_numbers = set()
        for question in item["questions"]:
            try:
                local_numbers.add(int(question.get("number")))
            except (TypeError, ValueError):
                continue
        if not local_numbers:
            continue
        tokens = _tokens(item["transcript"])
        ranked = sorted(groups,
                        key=lambda group: _jaccard(tokens, group["tokens"]),
                        reverse=True)
        best = None
        for group in ranked:
            if _jaccard(tokens, group["tokens"]) < MIN_ITEM_SCORE:
                break
            # 题号是强信号：本地题号和题库题组至少对上一半，才挂选项。
            overlap = local_numbers & set(group["questions"])
            if len(overlap) >= max(1, len(local_numbers) // 2):
                best = group
                break
        if best is None:
            continue
        questions = {}
        for number in sorted(local_numbers):
            payload = best["questions"].get(number)
            if payload:
                questions[str(number)] = payload
        if questions:
            items[f"{item['letter']}-{item['index']}"] = {"questions": questions}
    return items


def build(papers_root: pathlib.Path, db_path: pathlib.Path) -> dict:
    sources = _load_db(db_path)
    papers = []
    for path in sorted(papers_root.iterdir()):
        if path.is_dir():
            paper = _parse_paper(path / "data.js")
            if paper:
                papers.append(paper)
    out = {}
    report = []
    for paper in papers:
        source, ranked = _match_source(paper, sources)
        if source is None:
            report.append({"paper": paper["title"], "source": None,
                           "score": ranked[0][0] if ranked else 0.0,
                           "questions": 0})
            continue
        items = _map_items(paper, sources[source])
        count = sum(len(item["questions"]) for item in items.values())
        report.append({"paper": paper["title"], "source": source,
                       "score": next(row[0] for row in ranked if row[1] == source),
                       "questions": count})
        if items:
            out[paper["title"]] = {
                "source_file": source,
                "items": items,
            }
    return {"schema": SCHEMA, "source": SOURCE, "papers": out}, report


def _stub_reason(title: str) -> str:
    if re.search(r"^(201[6-8])年", title):
        return "题库覆盖 2019 年及以后"
    if "2026年06月" in title and "卷二" in title:
        return "本卷未匹配到题库"
    if "强化" in title or "讲座原声" in title:
        return "非真题卷，暂无做题数据"
    return "暂无做题数据"


def write_sidecars(papers_root: pathlib.Path, content: dict) -> int:
    written = 0
    for path in sorted(papers_root.iterdir()):
        if not path.is_dir() or not (path / "data.js").is_file():
            continue
        payload = content["papers"].get(path.name)
        if payload:
            value = {"schema": SCHEMA, "source": SOURCE["name"], **payload}
        else:
            value = {"schema": SCHEMA, "reason": _stub_reason(path.name)}
        text = "window.QUIZ = " + json.dumps(value, ensure_ascii=False) + ";\n"
        (path / "quiz.js").write_text(text, encoding="utf-8")
        written += 1
    return written


def render(report: list[dict], content: dict, sidecars: int | None = None) -> str:
    covered = [row for row in report if row["source"]]
    total_q = sum(row["questions"] for row in covered)
    lines = [f"本地试卷：{len(report)} 份",
             f"可做题：{len(covered)} 份 · {total_q} 题"]
    for row in report:
        if row["source"]:
            lines.append(f"  {row['paper']} -> {row['source']}"
                         f"（{row['score']:.3f}，{row['questions']} 题）")
        else:
            lines.append(f"  {row['paper']}：无数据（最高 {row['score']:.3f}）")
    if sidecars is not None:
        lines.append(f"已生成 quiz.js：{sidecars} 份（含无数据桩）")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="六级听力做题题库提取（只读默认）")
    parser.add_argument("--db", default="", help="Shepi 题库 SQLite 路径")
    parser.add_argument("--papers", default=str(config.cet6_dir() / "试卷"))
    parser.add_argument("--content", default=str(CONTENT))
    parser.add_argument("--apply", action="store_true", help="写 JSON / quiz.js")
    parser.add_argument("--sidecars", action="store_true", help="生成每卷 quiz.js")
    args = parser.parse_args(argv)

    papers_root = pathlib.Path(args.papers)
    content_path = pathlib.Path(args.content)
    if args.db:
        content, report = build(papers_root, pathlib.Path(args.db))
    else:
        if not content_path.is_file():
            print(f"题库 JSON 不存在：{content_path}（先带 --db 生成）")
            return 1
        content = json.loads(content_path.read_text(encoding="utf-8"))
        report = []
        for title, row in content.get("papers", {}).items():
            count = sum(len(item["questions"]) for item in row["items"].values())
            report.append({"paper": title, "source": row.get("source_file"),
                           "score": 0.0, "questions": count})
        for name in sorted(papers_root.iterdir()):
            if name.is_dir() and (name / "data.js").is_file() \
                    and name.name not in content.get("papers", {}):
                report.append({"paper": name.name, "source": None,
                               "score": 0.0, "questions": 0})

    sidecars = None
    if args.apply:
        content_path.write_text(
            json.dumps(content, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    if args.sidecars:
        if not args.apply:
            print("预检：生成 quiz.js 需要同时加 --apply。")
        else:
            sidecars = write_sidecars(papers_root, content)
    print(render(report, content, sidecars))
    if not args.apply:
        print("预检：加 --apply 才会写文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
