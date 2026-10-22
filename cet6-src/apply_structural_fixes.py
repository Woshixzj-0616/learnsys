# -*- coding: utf-8 -*-
"""应用 `校对/结构修复.json`：补句 / 删句 / 改起点终点，并重切受影响的 MP3。

新增句子用 1001+ 的独立 i，display 只负责界面显示，避免和用户已有句号冲突。
默认预演；加 --apply 才写文件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
TOOL = Path(__file__).resolve().parent
PAPERS = Path(r"D:\Desktop\六级精听\试卷")
FIXES = TOOL / "校对" / "结构修复.json"
DATA_PREFIX = "window.PAPER ="


def read_paper(paper_dir: Path) -> dict:
    text = (paper_dir / "data.js").read_text(encoding="utf-8").strip()
    if not text.startswith(DATA_PREFIX):
        raise ValueError("不是工作台 data.js")
    body = text[len(DATA_PREFIX):].strip()
    if body.endswith(";"):
        body = body[:-1]
    return json.loads(body)


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_paper(paper_dir: Path, paper: dict) -> None:
    body = json.dumps(paper, ensure_ascii=False, indent=2)
    write_atomic(paper_dir / "data.js", DATA_PREFIX + " " + body + ";\n")
    write_atomic(paper_dir / "时间轴.json", body + "\n")


def item_dir(paper_dir: Path, item: dict) -> Path:
    rel = (item.get("paths") or {}).get("content") or ""
    if rel:
        return (paper_dir / rel).parent
    raise ValueError("item 没有 paths.content，无法定位目录")


def sentence_path(idir: Path, i: int) -> Path:
    return idir / "句子" / f"{int(i):02d}.mp3"


def cut(ffmpeg: str, audio: Path, start: float, end: float, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp.mp3")
    subprocess.run(
        [ffmpeg, "-y", "-ss", f"{max(0.0, start):.3f}", "-to", f"{max(0.0, end):.3f}",
         "-i", str(audio), "-vn", "-acodec", "libmp3lame", "-q:a", "4", str(tmp)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    shutil.move(str(tmp), str(dest))


def main() -> int:
    parser = argparse.ArgumentParser(description="应用结构补句/删句")
    parser.add_argument("--apply", action="store_true", help="真正写入；不加只预演")
    parser.add_argument("--fixes", default=str(FIXES))
    args = parser.parse_args()

    data = json.loads(Path(args.fixes).read_text(encoding="utf-8"))
    ops = data.get("items") or []
    if not ops:
        print("没有结构修复操作。")
        return 0

    # 按试卷分组，一次读写一份 data.js
    by_paper: dict[str, list[dict]] = {}
    for op in ops:
        by_paper.setdefault(str(op.get("paper") or ""), []).append(op)

    total_ins = total_rem = total_upd = 0
    for title, paper_ops in by_paper.items():
        pdir = PAPERS / title
        if not pdir.is_dir():
            print(f"✗ 找不到试卷：{title}")
            return 1
        paper = read_paper(pdir)
        sections = paper.get("sections") or []
        sig = hashlib.sha1(
            json.dumps(paper_ops, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        if (paper.get("structural_fixes") or {}).get("signature") == sig:
            print(f"\n=== {title} === 已应用过（签名 {sig}），跳过")
            continue
        print(f"\n=== {title} === 签名 {sig}")
        for op in paper_ops:
            unit = str(op.get("unit") or "")
            item = None
            for sec in sections:
                for cur in sec.get("items") or []:
                    if cur.get("title") == unit:
                        item = cur
                        break
                if item:
                    break
            if item is None:
                print(f"✗ 找不到单元：{unit}")
                return 1
            sents = item.get("sentences") or []
            idir = item_dir(pdir, item)
            audio = pdir / "audio.mp3"
            changed = False

            # 1) 更新已有句子
            for upd in op.get("update") or []:
                i = int(upd.get("i"))
                s = next((x for x in sents if int(x.get("i", -1)) == i), None)
                if s is None:
                    print(f"✗ {unit} 没有第 {i} 句")
                    return 1
                for key in ("en", "start", "end"):
                    if key in upd:
                        s[key] = upd[key]
                changed = True
                total_upd += 1
                print(f"  更新 {unit} 第 {i} 句")

            # 2) 删除句子
            for i in op.get("remove") or []:
                i = int(i)
                s = next((x for x in sents if int(x.get("i", -1)) == i), None)
                if s is None:
                    print(f"  跳过删除：{unit} 没有第 {i} 句")
                    continue
                sents.remove(s)
                if args.apply:
                    try:
                        sentence_path(idir, i).unlink(missing_ok=True)
                    except OSError:
                        pass
                changed = True
                total_rem += 1
                print(f"  删除 {unit} 第 {i} 句：{s.get('en','')[:60]}")

            # 3) 插入句子（按 after 定位；after=0 表示最前面）
            for ins in op.get("insert") or []:
                after = int(ins.get("after") or 0)
                if after == 0:
                    pos = 0
                else:
                    pos = next((k + 1 for k, x in enumerate(sents)
                                if int(x.get("i", -1)) == after), None)
                    if pos is None:
                        print(f"✗ {unit} 找不到 after={after}")
                        return 1
                row = {
                    "i": int(ins["i"]),
                    "display": str(ins["display"]),
                    "start": float(ins["start"]),
                    "end": float(ins["end"]),
                    "en": str(ins["en"]),
                    "align": 1.0,
                    "review": False,
                    "review_reasons": [],
                }
                sents.insert(pos, row)
                changed = True
                total_ins += 1
                print(f"  插入 {unit} {row['display']}（i={row['i']}）")

            # 4) 内容区间
            if op.get("content_start") is not None:
                item["content"]["start"] = float(op["content_start"])
                changed = True
            if op.get("content_end") is not None:
                item["content"]["end"] = float(op["content_end"])
                changed = True

            if not changed or not args.apply:
                continue

            # 5) 重切插入/更新过时间的句子，以及正文
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            touched = {int(x["i"]) for x in (op.get("insert") or [])}
            touched |= {int(x["i"]) for x in (op.get("update") or [])
                        if "start" in x or "end" in x}
            for idx, s in enumerate(sents):
                if int(s.get("i", -1)) not in touched:
                    continue
                start = max(0.0, float(s.get("start") or 0) - 0.2)
                if idx + 1 < len(sents):
                    nxt = float(sents[idx + 1].get("start") or s.get("end") or 0)
                    end = max(float(s.get("end") or 0),
                              min(float(s.get("end") or 0) + 0.35, nxt))
                else:
                    end = float(s.get("end") or 0) + 0.2
                cut(ffmpeg, audio, start, end, sentence_path(idir, int(s["i"])))
            if op.get("content_start") is not None or op.get("content_end") is not None:
                content = item.get("content") or {}
                cut(ffmpeg, audio, max(0.0, float(content.get("start") or 0) - 0.2),
                    float(content.get("end") or 0) + 0.2, idir / "正文.mp3")

        net = 0
        for sec in sections:
            for it in sec.get("items") or []:
                net += 0  # 句子数由实际数组决定
        if args.apply:
            paper.setdefault("stats", {})["sentences"] = sum(
                len(it.get("sentences") or []) for sec in sections for it in sec.get("items") or [])
            paper.setdefault("structural_fixes", {})
            paper["structural_fixes"]["checked_at"] = data.get("checked_at", "")
            paper["structural_fixes"]["count"] = sum(
                len(op.get("insert") or []) + len(op.get("remove") or []) for op in paper_ops)
            paper["structural_fixes"]["signature"] = sig
            paper["structural_fixes"]["applied"] = True
            write_paper(pdir, paper)
            print(f"  已写入：{pdir / 'data.js'}")

    print(f"\n汇总：插入 {total_ins} 句，删除 {total_rem} 句，更新 {total_upd} 句。")
    if not args.apply:
        print("这是预演；确认后加 --apply 真正写入并重切 MP3。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
