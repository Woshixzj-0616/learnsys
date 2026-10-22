# -*- coding: utf-8 -*-
"""用 base.en 重新转写一小段音频，供原文校对时确认个别词。

用法：
  D:\\cet6_tool\\.venv\\Scripts\\python.exe 转写片段.py --title "试卷标题" --start 69 --end 76
  ... --dir "D:\\Desktop\\六级精听\\试卷\\某卷" --start 100 --end 120

注意：base.en 也会听错；它只用来确认「有没有这个词 / 是不是这个音」。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_PAPERS = Path(r"D:\Desktop\六级精听\试卷")
DEFAULT_MODEL = Path(r"D:\cet6_tool\models\base.en")


def pick_dir(args) -> Path:
    if args.dir:
        return Path(args.dir).expanduser().resolve()
    root = Path(args.papers).expanduser().resolve()
    exact = root / args.title
    if exact.is_dir():
        return exact
    hits = [p for p in root.iterdir() if p.is_dir() and args.title in p.name]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"找不到试卷：{args.title}（{root}）")
    names = "、".join(p.name for p in hits[:8])
    raise SystemExit(f"标题匹配到多份试卷，请写完整：{names}")


def main() -> int:
    parser = argparse.ArgumentParser(description="转写试卷的一小段音频")
    parser.add_argument("--title", default="", help="试卷标题或标题片段")
    parser.add_argument("--dir", default="", help="直接指定试卷目录")
    parser.add_argument("--papers", default=str(DEFAULT_PAPERS), help="试卷根目录")
    parser.add_argument("--start", type=float, required=True, help="起始秒")
    parser.add_argument("--end", type=float, required=True, help="结束秒")
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="Whisper 模型目录")
    args = parser.parse_args()
    if not args.dir and not args.title:
        parser.error("需要 --title 或 --dir")
    if args.end <= args.start:
        parser.error("--end 必须大于 --start")

    paper_dir = pick_dir(args)
    audio = paper_dir / "audio.mp3"
    if not audio.is_file():
        raise SystemExit(f"找不到音频：{audio}")

    # faster-whisper 1.2.1 与 PyAV 19 的兼容 shim（与 split_listening.py 相同）
    import av
    _original_av_open = av.open

    def _compat_av_open(*a, **kw):
        kw.pop("metadata_errors", None)
        return _original_av_open(*a, **kw)

    av.open = _compat_av_open

    from faster_whisper import WhisperModel
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    clip = Path(tempfile.gettempdir()) / ("cet6_clip_%s_%s.wav" % (args.start, args.end))
    subprocess.run(
        [ffmpeg, "-y", "-ss", str(args.start), "-to", str(args.end),
         "-i", str(audio), str(clip)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    model_path = Path(args.model)
    if not model_path.exists():
        raise SystemExit(f"找不到模型：{model_path}")
    model = WhisperModel(str(model_path), device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(clip), word_timestamps=True, language="en", vad_filter=False)

    print(f"试卷：{paper_dir.name}")
    print(f"片段：{args.start:.3f}–{args.end:.3f} 秒")
    for seg in segments:
        print(f"\n[{seg.start + args.start:.2f}–{seg.end + args.start:.2f}] {seg.text.strip()}")
        for word in seg.words:
            print(f"  {word.start + args.start:8.2f} {word.end + args.start:8.2f}  {word.word}")
    try:
        clip.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
