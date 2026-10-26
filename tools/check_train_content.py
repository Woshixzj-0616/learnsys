"""训练内容包校验：字段、长度、id 唯一、信息点覆盖、句子数量。

    .venv/Scripts/python.exe -X utf8 tools/check_train_content.py
    ... --dir path/to/content --json

通过返回 0，失败返回 1。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys.train import content, validate            # noqa: E402

LABELS = (
    ("writing", "写作内容包"),
    ("translation", "翻译内容包"),
    ("extra_sentences", "技能专项句"),
    ("derived_sentences", "篇目派生句"),
    ("sentences", "一句一译总数"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验六级写作/翻译训练内容包")
    parser.add_argument("--dir", default="", help="内容目录（默认 learnsys/train/content）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    target = pathlib.Path(args.dir).resolve() if args.dir else None
    lib = content.library(target)
    errors = validate.check_library(lib, target)
    counts = validate.counts(lib, target)
    if args.json:
        print(json.dumps({"ok": not errors, "counts": counts, "errors": errors},
                         ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    print("学习工作台 · 训练内容校验")
    for key, label in LABELS:
        print(f"  {label}：{counts.get(key, 0)}")
    print(f"  内容版本：{counts.get('version', '')}")
    if errors:
        print(f"失败：{len(errors)} 项")
        for row in errors:
            print(f"  - {row}")
        return 1
    print("通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
