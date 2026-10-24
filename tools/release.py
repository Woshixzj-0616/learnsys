# -*- coding: utf-8 -*-
r"""把 dist\学习工作台\ 打成可发布的 zip，排除个人数据，并生成 SHA256。

用法：
    .venv\\Scripts\\python.exe tools\\release.py
    .venv\\Scripts\\python.exe tools\\release.py --version 2.0.0
    .venv\\Scripts\\python.exe tools\\release.py --check-only

发布卫生：
- 不含 设置.json / *.db / 截图 / 录音 / 真题音频 / 模型权重；
- 打印包内文件数与大小，写同名 .sha256。
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "学习工作台"
EXCLUDE_DIRS = {"data", "models", "截图", "问答截图", "录屏", "报告", "备份"}
EXCLUDE_SUFFIXES = {".db", ".db-wal", ".db-shm", ".mp3", ".wav", ".m4a", ".log"}
EXCLUDE_NAMES = {"设置.json", "界面设置.json", "学习档案.md"}


def version_from_code() -> str:
    sys.path.insert(0, str(ROOT))
    from learnsys.product import VERSION
    return VERSION


def blocked(path: pathlib.Path, base: pathlib.Path) -> bool:
    rel = path.relative_to(base)
    # 只排「发布目录顶层」的个人数据目录；_internal/cv2/data 这类库文件不能误伤
    if rel.parts and rel.parts[0] in EXCLUDE_DIRS:
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    return path.suffix.lower() in EXCLUDE_SUFFIXES


def main() -> int:
    parser = argparse.ArgumentParser(description="生成发布 zip + SHA256")
    parser.add_argument("--version", default=version_from_code())
    parser.add_argument("--dist", default=str(DIST))
    parser.add_argument("--check-only", action="store_true",
                        help="只检查包里有没有个人数据，不写 zip")
    args = parser.parse_args()

    base = pathlib.Path(args.dist)
    if not (base / "学习工作台.exe").exists():
        print(f"没找到打包产物：{base / '学习工作台.exe'}；先跑到 打包.cmd。")
        return 1

    files, skipped = [], []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if blocked(path, base):
            skipped.append(path.relative_to(base).as_posix())
        else:
            files.append(path)

    if skipped:
        print(f"排除 {len(skipped)} 个个人数据/非发布文件（示例）：")
        for name in skipped[:12]:
            print("  -", name)
    else:
        print("没有需要排除的个人数据。")

    if args.check_only:
        print(f"可发布文件：{len(files)} 个，共 {sum(p.stat().st_size for p in files) / 1048576:.1f} MB")
        return 0

    out = ROOT / "dist" / f"学习工作台-v{args.version}-windows-x64.zip"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(base).as_posix())

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (out.with_suffix(out.suffix + ".sha256")).write_text(
        f"{digest}  {out.name}\n", encoding="utf-8")
    print(f"发布包：{out}（{out.stat().st_size / 1048576:.1f} MB）")
    print(f"SHA256：{digest}")
    print(f"清单：{out.with_suffix(out.suffix + '.sha256')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
