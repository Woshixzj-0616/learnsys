"""文件与代码执行工具：学习档案写入、代码沙箱。"""
from __future__ import annotations

import pathlib

from learnsys.agent import sandbox
from .context import ToolContext


STUDY_FILE_SUFFIXES = {".md", ".txt", ".cpp", ".cc", ".c", ".h", ".hpp",
                       ".py", ".json", ".csv"}
_STUDY_BAD_CHARS = set('<>:"|?*')


def _study_target(raw: str, data_root: pathlib.Path) -> tuple[pathlib.Path | None, str]:
    """把相对路径夹到「学习档案」里；拒绝绝对路径、`..` 和奇怪扩展名。"""
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return None, "没有给文件路径。"
    if text.startswith("/") or ":" in text:
        return None, "只能写「学习档案」里的相对路径，不能写绝对路径或盘符。"
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None, "只能写「学习档案」里的相对路径，不能包含 `..`。"
    if any(any(ch in _STUDY_BAD_CHARS for ch in part) or part.strip(".") == ""
           for part in parts):
        return None, "路径里有 Windows 不允许的字符。"
    suffix = pathlib.Path(parts[-1]).suffix.lower()
    if suffix not in STUDY_FILE_SUFFIXES:
        allowed = "、".join(sorted(STUDY_FILE_SUFFIXES))
        return None, f"不支持这个扩展名；只允许 {allowed}。"
    base = (pathlib.Path(data_root) / "学习档案").resolve()
    target = base.joinpath(*parts).resolve()
    if target != base and base not in target.parents:
        return None, "只能写「学习档案」里的相对路径。"
    return target, ""


def write_study_file(relative_path: str, content: str, *,
                     ctx: ToolContext) -> str:
    """写「学习档案」下的文本文件；原子替换，失败给中文原因。"""
    body = str(content or "")
    if len(body) > 200_000:
        return "文件太长（上限 20 万字），没有保存。"
    target, reason = _study_target(relative_path, ctx.data_root)
    if target is None:
        return reason
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(body, encoding="utf-8")
        temp.replace(target)
    except OSError as exc:
        return f"写文件失败：{exc}"
    relative = target.relative_to((pathlib.Path(ctx.data_root) / "学习档案").resolve())
    return f"已保存到 学习档案/{relative.as_posix()}（{len(body)} 字）。"


def run_code(language: str, code: str, stdin: str = "",
             *, ctx: ToolContext) -> str:
    """在临时目录跑一段代码；结果（含失败原因）给模型和审计。"""
    # 代码调试轮：坏 stdin 很常见，5 秒足够跑完学习级程序；不给它 10 秒死等。
    timeout = 5.0 if getattr(ctx, "code_debug", False) else sandbox.DEFAULT_TIMEOUT
    result = sandbox.run(str(language or ""), str(code or ""),
                         stdin_text=str(stdin or ""), timeout=timeout)
    return result.render()
