"""个人资料导入：把「关于你」画像、日记、想法库变成带出处的事实。

零模型成本：只做 Markdown bullet / 段落解析，不调模型。
- 画像文档：active，confidence 0.95；
- 日记、想法库：candidate，confidence 0.55–0.6，等用户审核。
"""
from __future__ import annotations

import pathlib
import re

from learnsys import store

from .sources.common import clean_text

CAHIER = pathlib.Path(r"D:/cahier/智库/智库")
PROFILE_DIRS = (
    CAHIER / "Codex记忆系统" / "01-关于你",
    CAHIER / "CodeBuddy记忆系统" / "01-关于你",
    CAHIER / "MiMo记忆系统",
    pathlib.Path.home() / ".qwen" / "memories" / "user",
)
DIARY_DIR = CAHIER / "日记"
IDEA_DIR = CAHIER / "想法库"

_DIARY_SIGNALS = ("目标", "决定", "以后", "每次", "习惯", "计划", "不想",
                  "必须", "不能", "截止", "考试", "复盘", "教训", "坚持")
_PROFILE_SKIP = ("回到本文件夹", "上级", "本表只改", "原文快照", "30 秒速览")


def _clean_markdown(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("**", "").replace("`", "")
    value = re.sub(r"^[-*]\s*", "", value)
    return clean_text(value)


def _kind_for(path: pathlib.Path, content: str) -> str:
    name = path.name
    if "沟通" in name or "口味" in name:
        return "preference"
    if "身份" in name or "关于你" in name:
        return "identity"
    if "协作" in name or "元规则" in name or "记忆系统规矩" in name:
        return "rule"
    if "项目" in path.parts:
        return "project"
    if any(word in content for word in ("目标", "想过", "计划考", "要过")):
        return "goal"
    if any(word in content for word in ("不能", "不要", "禁止", "截止", "必须")):
        return "constraint"
    return "preference"


def _scope_for(path: pathlib.Path) -> str:
    parts = path.parts
    if "项目" in parts:
        index = parts.index("项目")
        if index + 1 < len(parts):
            return f"project:{parts[index + 1]}"
    return "global"


def parse_bullets(path: pathlib.Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    facts: list[dict] = []
    for number, line in enumerate(lines, 1):
        raw = line.strip()
        if not raw.startswith(("- ", "* ")):
            continue
        text = _clean_markdown(raw)
        if len(text) < 6 or any(skip in text for skip in _PROFILE_SKIP):
            continue
        if text.startswith(("http://", "https://")):
            continue
        facts.append({
            "content": text[:500],
            "kind": _kind_for(path, text),
            "scope": _scope_for(path),
            "evidence": f"profile:{path}#L{number}",
            "source": "profile_md",
            "source_ref": str(path),
            "confidence": 0.95,
            "status": "active",
        })
    return facts


def _paragraphs(path: pathlib.Path):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    block: list[str] = []
    start = 1
    for number, line in enumerate(lines, 1):
        if line.strip():
            if not block:
                start = number
            block.append(line.strip())
        elif block:
            yield start, " ".join(block)
            block = []
    if block:
        yield start, " ".join(block)


def parse_diary(path: pathlib.Path, limit: int = 3) -> list[dict]:
    facts: list[dict] = []
    for line, paragraph in _paragraphs(path):
        text = _clean_markdown(paragraph)
        if not (15 <= len(text) <= 500):
            continue
        if not any(signal in text for signal in _DIARY_SIGNALS):
            continue
        kind = "goal" if any(w in text for w in ("目标", "计划", "要过")) else (
            "constraint" if any(w in text for w in ("必须", "不能", "不要", "截止"))
            else "preference")
        facts.append({
            "content": text, "kind": kind, "scope": "global",
            "evidence": f"diary:{path}#L{line}",
            "source": "diary", "source_ref": str(path),
            "confidence": 0.55, "status": "candidate",
        })
        if len(facts) >= limit:
            break
    return facts


def import_profiles(conn, *, dry_run: bool = False) -> dict:
    paths: list[pathlib.Path] = []
    for folder in PROFILE_DIRS:
        if folder.exists():
            paths.extend(sorted(
                path for path in folder.glob("*.md")
                if not path.name.startswith("00-索引")
                and path.name.lower() != "readme.md"))
    facts = []
    for path in paths:
        facts.extend(parse_bullets(path))
    added = merged = 0
    if not dry_run:
        for fact in facts:
            memory_id, created = store.add_memory(
                conn, fact["content"], fact["kind"], scope=fact["scope"],
                evidence=fact["evidence"], confidence=fact["confidence"],
                source=fact["source"], source_ref=fact["source_ref"],
                status=fact["status"])
            if memory_id and created:
                added += 1
            elif memory_id:
                merged += 1
    return {"files": len(paths), "facts": len(facts),
            "added": added, "merged": merged}


def import_diaries(conn, *, limit: int = 200, dry_run: bool = False) -> dict:
    paths = sorted(DIARY_DIR.glob("**/*.md"), reverse=True) if DIARY_DIR.exists() else []
    facts = []
    for path in paths:
        facts.extend(parse_diary(path))
        if len(facts) >= limit:
            break
    facts = facts[:limit]
    added = merged = 0
    if not dry_run:
        for fact in facts:
            memory_id, created = store.add_memory(
                conn, fact["content"], fact["kind"], evidence=fact["evidence"],
                confidence=fact["confidence"], source=fact["source"],
                source_ref=fact["source_ref"], status=fact["status"])
            if memory_id and created:
                added += 1
            elif memory_id:
                merged += 1
    return {"files": len(paths), "facts": len(facts),
            "added": added, "merged": merged}


def import_ideas(conn, *, dry_run: bool = False) -> dict:
    paths = sorted(IDEA_DIR.glob("*.md")) if IDEA_DIR.exists() else []
    facts = []
    for path in paths:
        for item in parse_bullets(path):
            item.update({"status": "candidate", "confidence": 0.6,
                         "source": "idea"})
            facts.append(item)
    added = merged = 0
    if not dry_run:
        for fact in facts:
            memory_id, created = store.add_memory(
                conn, fact["content"], fact["kind"], evidence=fact["evidence"],
                confidence=fact["confidence"], source=fact["source"],
                source_ref=fact["source_ref"], status=fact["status"])
            if memory_id and created:
                added += 1
            elif memory_id:
                merged += 1
    return {"files": len(paths), "facts": len(facts),
            "added": added, "merged": merged}
