"""设计令牌装载（R3.10.1）。

Qt 外观的**唯一来源**是 `web/css/tokens.css`：运行时读出来填进 QSS，Qt 里不另抄一份配色表。
读不到时用本文件的兜底值（只保证不崩、不白闪，不当作第二份主题维护）。
"""
from __future__ import annotations

import pathlib
import re

from learnsys.modules import web_dir

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_ROOT_BLOCK = re.compile(r":root\s*\{([^{}]*)\}", re.S)
_MOOD_BLOCK = re.compile(r'body\[data-mood="([\w-]+)"\]\s*\{([^{}]*)\}', re.S)
_DECLARATION = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")

# 仅在读不到 tokens.css 时使用；值抄自同一文件的「墨夜」（快捷栏固定用这套）
_FALLBACK = {
    "--bg": "#12151a",
    "--bg-raised": "#1b1f26",
    "--bg-sunken": "#171b21",
    "--bg-input": "#171b21",
    "--surface": "#1b1f26",
    "--surface-2": "#20252d",
    "--line": "rgba(255, 255, 255, 0.07)",
    "--line-strong": "rgba(255, 255, 255, 0.13)",
    "--text": "#e8eef6",
    "--text-dim": "#a3b0c0",
    "--text-faint": "#7d8a9a",
    "--accent": "#6d9bff",
    "--accent-strong": "#8ab0ff",
    "--accent-soft": "rgba(109, 155, 255, 0.14)",
    "--accent-line": "rgba(109, 155, 255, 0.42)",
    "--on-accent": "#ffffff",
    "--mark": "#f0b45e",
    "--mark-soft": "rgba(240, 180, 94, 0.14)",
    "--ok": "#5cc08b",
    "--warn": "#e0a35c",
    "--err": "#e37b7b",
    "--err-soft": "rgba(227, 123, 123, 0.12)",
    "--fs-xs": "12px",
    "--fs-sm": "13px",
    "--fs-base": "15px",
    "--fs-md": "16px",
    "--fs-lg": "20px",
    "--fs-xl": "28px",
    "--s1": "4px",
    "--s2": "8px",
    "--s3": "12px",
    "--s4": "16px",
    "--s5": "24px",
    "--s6": "32px",
    "--s7": "48px",
    "--r-sm": "6px",
    "--r-md": "10px",
    "--r-lg": "14px",
    "--measure": "820px",
    "--font-ui": '"Microsoft YaHei UI", "微软雅黑", "PingFang SC", system-ui, sans-serif',
}

# QSS / 布局真正读到的键；缺了这些说明未配置好
REQUIRED = (
    "--bg", "--bg-raised", "--bg-sunken", "--bg-input",
    "--surface", "--surface-2",
    "--line", "--line-strong",
    "--text", "--text-dim", "--text-faint",
    "--accent", "--accent-strong", "--accent-soft", "--accent-line", "--on-accent",
    "--err", "--err-soft", "--ok",
    "--fs-xs", "--fs-sm", "--fs-base", "--fs-md", "--fs-lg",
    "--s1", "--s2", "--s3", "--s4", "--s5",
    "--r-sm", "--r-md", "--r-lg",
    "--font-ui",
)


def load_tokens(text: str) -> dict[str, str]:
    """解析 `:root { --name: value; }`；注释和别处的同名声明都不算。

    只认 `--名字: 值;`，值里的逗号、括号（`rgba(...)`）原样保留。
    """
    clean = _COMMENT.sub("", text or "")
    result: dict[str, str] = {}
    for block in _ROOT_BLOCK.findall(clean):
        for match in _DECLARATION.finditer(block):
            result[match.group(1)] = match.group(2).strip()
    return result


def load_mood_tokens(text: str, mood: str = "ink") -> dict[str, str]:
    """解析 `body[data-mood="ink"] { ... }` 这一块。

    网页切气质靠这段覆盖 `:root`；Qt 想跟某一套气质走时也读同一块。
    """
    clean = _COMMENT.sub("", text or "")
    result: dict[str, str] = {}
    for name, block in _MOOD_BLOCK.findall(clean):
        if name == mood:
            for match in _DECLARATION.finditer(block):
                result[match.group(1)] = match.group(2).strip()
    return result


def default_tokens() -> dict[str, str]:
    """内置兜底值。只在 `tokens.css` 读不到时使用。"""
    return dict(_FALLBACK)


def read_web_tokens(path: pathlib.Path | str | None = None,
                    mood: str | None = None) -> dict[str, str]:
    """读 `web/css/tokens.css`（打包后是 `_MEIPASS/web/...`），失败回退兜底。

    `mood` 非空时再用同名 `body[data-mood=...]` 块覆盖 `:root`。
    """
    target = pathlib.Path(path) if path is not None else web_dir() / "css" / "tokens.css"
    tokens = default_tokens()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return tokens
    tokens.update(load_tokens(text))
    if mood:
        tokens.update(load_mood_tokens(text, mood))
    return tokens


def merged(tokens: dict[str, str] | None = None) -> dict[str, str]:
    """兜底 + 自定义，保证 QSS 需要的键一个不少。"""
    result = default_tokens()
    if tokens:
        result.update(tokens)
    return result


def px(tokens: dict[str, str], name: str, default: int = 0) -> int:
    """把 `12px` 这类令牌转成 Qt 布局用的逻辑像素，失败用 default。"""
    raw = str(tokens.get(name) or "").strip().lower()
    if raw.endswith("px"):
        try:
            return int(round(float(raw[:-2])))
        except ValueError:
            return default
    return default


def font_family(tokens: dict[str, str]) -> str:
    """`--font-ui` 是 CSS 字体列表；跳过 mac 专用族，选 Windows 能命中的第一个。"""
    raw = str(tokens.get("--font-ui") or "")
    names = [part.strip().strip('"').strip("'") for part in raw.split(",") if part.strip()]
    for name in names:
        if name in {"-apple-system", "system-ui", "sans-serif", "Segoe UI"}:
            continue
        if not name.startswith("-"):
            return name
    return "Microsoft YaHei UI"
