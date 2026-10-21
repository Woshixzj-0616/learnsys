"""资料检索：候选召回 → 相关性重排 → 命中段（snippet）+ 页码。

借了「智能旅行」检索层的三条尺子，但不引入联网源和向量库：
1. **实体整体命中**优先：「子网划分」整体出现，比只命中「子网」「划分」更相关；
2. **关键词重合**做第二把尺子，中文按二元组、英文按单词；
3. **snippet 带页码**：PDF 用 `\\f` 分页、PPTX 用「--- 第 N 页 ---」分页，命中位置能算回页号。

纯函数在文件上半段，`search(conn, ...)` 才碰数据库 —— 测试不用起服务。
"""
from __future__ import annotations

import re
import sqlite3

CJK = re.compile(r"[一-鿿]")
CJK_RUN = re.compile(r"[一-鿿]{2,}")
WORD = re.compile(r"[a-z0-9]{2,}")
PAGE_MARK = re.compile(r"---\s*第\s*(\d+)\s*页\s*---")


def tokens(text: str) -> set[str]:
    """检索词切分：英文数字按词，中文按二元组（不引第三方分词）。"""
    low = (text or "").lower()
    cjk = CJK.findall(low)
    bigrams = {a + b for a, b in zip(cjk, cjk[1:]) if a.strip() and b.strip()}
    return set(WORD.findall(low)) | bigrams


def cjk_runs(text: str) -> list[str]:
    """查询里的中文连续段（≥2 字），用于「实体整体命中」。"""
    return CJK_RUN.findall(text or "")


def entity_hit(runs: list[str], text: str) -> int:
    """查询里的中文段在文本里最长整体命中几个字（0 = 一个都没整体命中）。"""
    best, low = 0, (text or "").lower()
    for run in runs:
        if len(run) > best and run in low:
            best = len(run)
    return best


def overlap(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & tokens(text)) / float(len(query_tokens))


def page_at(text: str, index: int) -> int:
    """正文位置 → 页码：PDF 数换页符，PPTX 数「--- 第 N 页 ---」。"""
    index = max(0, min(int(index or 0), len(text or "")))
    head = (text or "")[:index]
    if "\f" in text:
        return head.count("\f") + 1
    marks = list(PAGE_MARK.finditer(head))
    if marks:
        try:
            return int(marks[-1].group(1))
        except ValueError:
            return 0
    return 0


def _flatten(text: str) -> str:
    """snippet 用：换页符换空格、连续空白压成一个。"""
    return re.sub(r"\s+", " ", (text or "").replace("\f", " ")).strip()


def snippet_at(text: str, index: int, length: int = 280) -> str:
    """命中位置前后各取一段；位置越界就取开头。"""
    text = text or ""
    index = max(0, min(int(index or 0), len(text)))
    start = max(0, index - length // 2)
    end = min(len(text), start + length)
    piece = _flatten(text[start:end])
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + piece + suffix


def _first_pos(text: str, query: str, runs: list[str], q_tokens: set[str]) -> int:
    """按「整体查询 → 最长中文段 → 任一关键词」的顺序找第一个命中位置。"""
    low = (text or "").lower()
    if query and query.lower() in low:
        return low.find(query.lower())
    for run in sorted(runs, key=len, reverse=True):
        pos = low.find(run.lower())
        if pos >= 0:
            return pos
    for token in q_tokens:
        pos = low.find(token)
        if pos >= 0:
            return pos
    return 0


def _score(row: dict, query: str, runs: list[str], q_tokens: set[str]) -> float:
    title = str(row.get("title") or "")
    body = str(row.get("body") or "")
    tags = f"{row.get('tags') or ''} {row.get('course') or ''}"
    haystack = f"{title}\n{body}\n{tags}"
    low_q = (query or "").lower()
    score = 0.0
    if low_q and low_q in title.lower():
        score += 8
    if low_q and low_q in body.lower():
        score += 5
    score += min(entity_hit(runs, title), 12) * 0.6
    score += min(entity_hit(runs, body), 20) * 0.25
    score += overlap(q_tokens, tags) * 3
    score += overlap(q_tokens, title) * 2
    score += overlap(q_tokens, body) * 2
    if not score and not query:
        score = 1
    return round(score, 3)


def rank(rows: list[dict], query: str = "", limit: int = 8) -> list[dict]:
    """候选资料 → 按相关性排序的命中段；同一份资料最多两条，避免刷屏。"""
    query = (query or "").strip()
    runs = cjk_runs(query)
    q_tokens = tokens(query)
    ranked = []
    for row in rows:
        body = str(row.get("body") or "")
        score = _score(row, query, runs, q_tokens)
        if query and score <= 0:
            continue
        pos = _first_pos(body, query, runs, q_tokens)
        ranked.append({
            "material_id": int(row.get("id") or 0),
            "title": row.get("title") or "未命名资料",
            "kind": row.get("kind") or "",
            "course": row.get("course") or "",
            "tags": row.get("tags") or "",
            "page": page_at(body, pos),
            "snippet": snippet_at(body, pos),
            "updated_at": row.get("updated_at") or "",
            "score": score,
        })
    ranked.sort(key=lambda hit: (hit["score"], hit["updated_at"]), reverse=True)
    limit = max(1, min(int(limit or 8), 50))
    out, per = [], {}
    for hit in ranked:
        if per.get(hit["material_id"], 0) >= 2:
            continue
        per[hit["material_id"]] = per.get(hit["material_id"], 0) + 1
        out.append(hit)
        if len(out) >= limit:
            break
    return out


def _terms(query: str) -> list[str]:
    """SQL 候选召回用的词：整句 + 中文段 + 二元组 + 英文词。"""
    query = (query or "").strip()
    out: list[str] = []
    for term in [query, *cjk_runs(query), *tokens(query)]:
        term = term.strip()
        if term and term not in out:
            out.append(term)
    return out[:12]


def search(conn: sqlite3.Connection, query: str = "", limit: int = 8) -> list[dict]:
    """在统一库里搜资料；空查询 = 最近资料。"""
    query = (query or "").strip()
    terms = _terms(query)
    params: list[str] = []
    where = ["status = 'active'"]
    for term in terms:
        where.append("(title LIKE ? OR body LIKE ? OR tags LIKE ? OR course LIKE ?)")
        pattern = f"%{term}%"
        params.extend([pattern, pattern, pattern, pattern])
    sql = ("SELECT id, title, kind, body, tags, course, updated_at FROM materials "
           "WHERE " + " AND ".join(where[:1]) + " AND (" + " OR ".join(where[1:]) + ") "
           "ORDER BY updated_at DESC LIMIT 300") if len(where) > 1 else (
           "SELECT id, title, kind, body, tags, course, updated_at FROM materials "
           "WHERE status = 'active' ORDER BY updated_at DESC LIMIT 50")
    rows = conn.execute(sql, params).fetchall()
    items = [{"id": row[0], "title": row[1], "kind": row[2], "body": row[3],
              "tags": row[4], "course": row[5], "updated_at": row[6]}
             for row in rows]
    return rank(items, query, limit=limit)
