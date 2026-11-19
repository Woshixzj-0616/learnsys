"""批改卡片的公共口径：哪些错误能建卡、背面怎么排必改点。"""
from __future__ import annotations

CARD_SEVERITIES = ("严重",)
# 审题/结构问题无法“独立重练”成一张卡，只留在提交记录里。
NON_CARD_TYPES = ("结构", "审题")


def error_lines(errors: list[dict]) -> str:
    lines = []
    for row in errors:
        line = f"- `{row['quote']}` → **{row['fix']}**"
        if row.get("why"):
            line += f"：{row['why']}"
        lines.append(line)
    return "\n".join(lines)
