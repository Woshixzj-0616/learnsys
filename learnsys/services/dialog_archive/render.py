"""对话总汇的 Markdown 渲染：动态围栏、锚点、索引、头信息。"""
from __future__ import annotations

import json
import re

ANCHOR_PREFIX = "learnsys:anchor"
BODY_START = "<!-- BODY START -->"
BODY_END = "<!-- END OF ARCHIVE -->"


def safe_id(text: str, limit: int = 120) -> str:
    value = re.sub(r"[^0-9A-Za-z._-]+", "_", str(text or "")).strip("_")
    return (value or "unknown")[:limit]


def anchor_for(archive_id: str, source: str, session_id: str, index: int = 0) -> str:
    tail = "s" if index <= 0 else f"m{index:04d}"
    return f"archive:{archive_id}/{source}/{safe_id(session_id)}/{tail}"


def fence_for(text: str) -> str:
    runs = [len(match.group(0)) for match in re.finditer(r"`+", text)]
    return "`" * max(3, (max(runs) + 1) if runs else 3)


def render_message(archive_id: str, source: str, session_id: str,
                   index: int, message) -> str:
    anchor = anchor_for(archive_id, source, session_id, index)
    role = "用户" if message.role == "user" else "助手"
    stamp = message.at or "时间未知"
    fence = fence_for(message.text)
    return (
        f"<!-- {ANCHOR_PREFIX} {anchor} -->\n"
        f"#### m{index:04d} · {role} · {stamp}\n\n"
        f"{fence}text\n{message.text}\n{fence}\n")


def render_session(archive_id: str, source: str, section: str, number: int,
                   session) -> str:
    heading_date = (session.at or "")[:10] or "日期未知"
    title = (session.title or session.session_id or "未命名").replace("\n", " ")
    lines = [
        f"### {section}-{number:04d} · {heading_date} · {title[:60]}",
        f"<!-- {ANCHOR_PREFIX} {anchor_for(archive_id, source, session.session_id)} -->",
        f"- 来源：{source}",
        f"- 源文件：{session.path}",
        f"- 会话 id：{session.session_id}",
        f"- 时间：{session.at or '未知'}",
        f"- 收录：{len(session.messages)} 条；跳过：{session.skipped} 条",
        "",
    ]
    body = [line + "\n" for line in lines]
    for index, message in enumerate(session.messages, 1):
        body.append(render_message(
            archive_id, source, session.session_id, index, message) + "\n")
    return "".join(body)


def render_body(archive_id: str, ordered: list[tuple[str, str, list]]) -> tuple[str, list[dict]]:
    """返回 `(正文, 会话索引行)`；正文从 BODY_START 后第一行开始计行号。"""
    chunks: list[str] = []
    rows: list[dict] = []
    line = 0
    for source, label, sections in ordered:
        if not sections:
            continue
        head = f"## {sections[0][0]}. {label}\n\n"
        chunks.append(head)
        line += head.count("\n")
        for section, _label, sessions in sections:
            for number, session in enumerate(sessions, 1):
                start = line + 1
                block = render_session(archive_id, source, section, number, session)
                chunks.append(block)
                line += block.count("\n")
                rows.append({
                    "line": start, "source": source, "section": section,
                    "session_id": session.session_id,
                    "title": session.title[:60],
                    "at": session.at, "messages": len(session.messages),
                    "anchor": anchor_for(archive_id, source, session.session_id),
                })
    chunks.append("\n" + BODY_END + "\n")
    return "".join(chunks), rows


def render_header(archive_id: str, created_at: str, cutoff_at: str,
                  body_sha256: str, body_bytes: int, body_chars: int,
                  sources: list[dict], total_sessions: int,
                  total_messages: int, redaction: dict[str, int],
                  rows: list[dict], missing: list[str]) -> str:
    lines = [
        "---",
        f"archive_id: {archive_id}",
        "schema: learnsys-dialog-archive/v1",
        "status: sealed",
        f"created_at: {created_at}",
        f"cutoff_at: {cutoff_at}",
        f'body_sha256: "{body_sha256}"',
        f"body_bytes: {body_bytes}",
        f"body_chars: {body_chars}",
        f"session_count: {total_sessions}",
        f"message_count: {total_messages}",
        "sources:",
    ]
    for item in sources:
        lines.append(
            "  - {id: %s, status: %s, files: %d, sessions: %d, "
            "messages: %d, chars: %d, errors: %d}" % (
                item["id"], item["status"], item["files"], item["sessions"],
                item["messages"], item["chars"], item["errors"]))
    if missing:
        lines.append("missing:")
        for text in missing:
            lines.append(f'  - {{id: doubao, status: missing, reason: "{text}"}}')
    lines += [
        "redaction:",
        "  rules: [email, phone, id_card, api_key, bearer, password]",
        f"  count: {sum(redaction.values())}",
        f"  detail: {json.dumps(redaction, ensure_ascii=False)}",
        'seal: "本档案不追加、不重写；新会话另建新档案，不改本文件"',
        "---",
        "",
        "# 对话总汇（封存）",
        "",
        "> 本文档一次性生成；正文为各来源 user/assistant 文本原文。",
        "> 证据引用格式：`archive:<archive_id>/<source>/<session_id>/m<NNNN>`。",
        "> 正文行号从 `BODY START` 后起算；锚点是更稳定的定位方式。",
        "",
        "## 索引",
        "",
        "### 来源汇总",
        "",
        "| 来源 | 状态 | 文件 | 会话 | 消息 | 正文字符 | 说明 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in sources:
        note = item.get("note", "")
        lines.append(
            f"| {item['id']} | {item['status']} | {item['files']} | "
            f"{item['sessions']} | {item['messages']} | {item['chars']} | {note} |")
    lines += ["", "### 缺失来源", "", "| 来源 | 状态 | 原因 |", "|---|---|---|"]
    if missing:
        for text in missing:
            lines.append(f"| doubao | missing | {text} |")
    else:
        lines.append("| - | - | 无 |")
    lines += ["", "### 会话索引", "",
              "| 正文行号 | 日期 | 来源 | 会话 | 标题 | 消息 | 锚点 |",
              "|---:|---|---|---|---|---:|---|"]
    for row in rows:
        lines.append(
            f"| {row['line']} | {(row['at'] or '')[:10]} | {row['source']} | "
            f"{safe_id(row['session_id'])} | {row['title'].replace('|', ' ')} | "
            f"{row['messages']} | `{row['anchor']}` |")
    lines += ["", BODY_START, ""]
    return "\n".join(lines)
