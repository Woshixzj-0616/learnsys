"""P29.2 HANDOFF 生成器：只拼指针与状态。

边界（必须守住）：
- 不调用模型；纯本地拼装，结果可复核；
- 只读仓库的固定入口文件与目录名，不遍历、不读业务代码；
- 只读外部记忆档的首段，正文永远给路径；
- 只写 `DATA_ROOT/projects/<name>/HANDOFF.md`，**绝不写回项目仓库**。
"""
from __future__ import annotations

import datetime
import pathlib
import re
import subprocess

from learnsys import config, store

MAX_CHARS = 6000
MAX_READ_BYTES = 64 * 1024
FIRST_PARA_CHARS = 200
MAX_FACTS = 3

DEFAULT_MEMORY_ROOT = pathlib.Path(r"D:\cahier\智库\智库\Codex记忆系统")
MEMORY_FILES = ("02-项目现状.md", "03-决策记录.md", "04-项目坑与经验.md")

_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    """项目名做目录名：去掉 Windows 非法字符与首尾点/空格。"""
    cleaned = _BAD_NAME.sub("_", str(name or "")).strip().strip(".")
    return cleaned or "未命名项目"


def memory_root() -> pathlib.Path:
    """外部记忆库根；`设置.json` 的 `handoff_memory_root` 可覆盖。"""
    raw = str(config.USER.get("handoff_memory_root") or "").strip()
    return pathlib.Path(raw).expanduser() if raw else DEFAULT_MEMORY_ROOT


def output_path(project: dict) -> pathlib.Path:
    return (config.DATA_ROOT / "projects" / safe_name(project.get("name"))
            / "HANDOFF.md")


def _first_paragraph(path: pathlib.Path, limit: int = FIRST_PARA_CHARS) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")[:MAX_READ_BYTES]
    body: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            if body:
                break
            continue
        body.append(line.lstrip("> -").strip())
        if sum(len(item) for item in body) >= limit:
            break
    return " ".join(body)[:limit]


def _git_commits(repo: pathlib.Path) -> list[str]:
    """最近 3 条提交；任何失败都静默省略，不影响生成。"""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "log", "-3", "--oneline"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=2)
    except Exception:
        return []
    if done.returncode != 0:
        return []
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def _repo_lines(repo: pathlib.Path) -> list[str]:
    if not repo.is_dir():
        return [f"- 路径：{repo}（路径失效）"]
    lines = [f"- 路径：{repo}"]
    for entry in ("README.md", "AGENTS.md", "CLAUDE.md"):
        if (repo / entry).is_file():
            lines.append(f"- 入口：{entry}")
    docs = repo / "docs" / "施工单"
    if docs.is_dir():
        # 按修改时间取最新；按文件名排会被中文名（如「闸门…」）排到字母之后。
        latest = sorted(docs.glob("*.md"),
                        key=lambda item: item.stat().st_mtime,
                        reverse=True)[:2]
        if latest:
            lines.append("- 最新施工单：" + "、".join(
                f"docs/施工单/{item.name}" for item in latest))
    if (repo / "docs" / "架构-前后端.md").is_file():
        lines.append("- 架构定位：docs/架构-前后端.md 第 7 节「改动定位表」")
    commits = _git_commits(repo)
    if commits:
        lines.append("- 最近提交：")
        lines.extend(f"  - {line}" for line in commits)
    return lines


def _memory_folder(name: str) -> pathlib.Path | None:
    """按项目名找外部记忆档；没有就返回 None（不猜别名）。"""
    root = memory_root()
    if not root.is_dir():
        return None
    folder = root / "项目" / safe_name(name)
    return folder if folder.is_dir() else None


def _memory_lines(name: str) -> list[str]:
    root = memory_root()
    if not root.is_dir():
        return [f"- 未配置外部记忆库：{root}（可在设置里填 `handoff_memory_root`）"]
    folder = _memory_folder(name)
    if folder is None:
        base = root / "项目"
        existing = (sorted(item.name for item in base.iterdir() if item.is_dir())
                    if base.is_dir() else [])
        hint = (f"；记忆库里现有项目档：{'、'.join(existing)}"
                if existing else "")
        return [f"- 未找到项目记忆档：{base / safe_name(name)}{hint}"]
    lines: list[str] = []
    for filename in MEMORY_FILES:
        path = folder / filename
        if not path.is_file():
            continue
        lines.append(f"- {filename[:-3]}：{path}")
        first = _first_paragraph(path)
        if first:
            lines.append(f"  {first}")
    return lines or [f"- 项目记忆档是空的：{folder}"]


def _fact_lines(conn, name: str) -> list[str]:
    """工作台自己的长期偏好里提到该项目的条目（最多 3 条）。"""
    hits = [fact for fact in store.list_facts(conn, limit=100)
            if name and name in str(fact.get("content") or "")]
    return [f"- {fact['content']}" for fact in hits[:MAX_FACTS]]


def build(conn, project: dict) -> str:
    """拼出一份 HANDOFF 文本；不写盘、不调模型。"""
    name = str(project.get("name") or "未命名项目")
    raw_repo = str(project.get("repo_path") or "").strip()
    lines = [
        f"# HANDOFF · {name}",
        f"> 自动生成，不手改；{datetime.datetime.now():%Y-%m-%d %H:%M}",
        "",
        "## 状态",
        f"- 状态：{project.get('status') or 'active'}",
        f"- 下一步：{project.get('next_step') or '未填写'}",
        f"- 风险：{project.get('risk') or '无'}",
        f"- 最近更新：{project.get('updated_at') or ''}",
        "",
        "## 仓库指针",
    ]
    lines.extend(_repo_lines(pathlib.Path(raw_repo)) if raw_repo
                 else ["- 未填写仓库路径"])
    lines.extend(["", "## 外部记忆（只读）"])
    lines.extend(_memory_lines(name))
    facts = _fact_lines(conn, name)
    if facts:
        lines.extend(["", "## 工作台偏好"])
        lines.extend(facts)
    lines.extend([
        "",
        "## 交接约定",
        "- 先在仓库根读 AGENTS.md / README.md，再按上面的指针看具体文件；",
        "- 改代码前查 `docs/架构-前后端.md` 第 7 节「改动定位表」；",
        "- 交接页是快照，与仓库冲突时以仓库为准。",
    ])
    text = "\n".join(lines).strip() + "\n"
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n（已截断，完整内容请看仓库与外部记忆。）\n"
    return text


def write(conn, project: dict) -> tuple[str, pathlib.Path]:
    """生成并落盘；同时把路径回写到 project_refs.handoff_path。"""
    text = build(conn, project)
    target = output_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    store.update_project(conn, int(project["id"]), handoff_path=str(target))
    return text, target
