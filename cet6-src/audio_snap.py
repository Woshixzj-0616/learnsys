# -*- coding: utf-8 -*-
"""按真实静音区校正逐句起止时间。

背景：Whisper 的 word.end 普遍偏早（实测句尾平均早 0.19s，p75 0.30s，个别 0.5s），
工作台按 start/end 精确截取播放，导致句尾被切。这里用 ffmpeg silencedetect
找到真实停顿，把句尾吸附到停顿边缘，并留少量余量。

本模块是唯一实现：`split_listening.py` 切新音频时调用 `snap_ends`，
`_snap_sentences.py` 批量修旧卷时调用 `snap` / `snap_ends`。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

NOISE = "-35dB"
MIN_SIL = 0.12

_SIL_START = re.compile(r"silence_start: ([\d.]+)")
_SIL_END = re.compile(r"silence_end: ([\d.]+)")


def parse_silences(text: str) -> list[tuple[float, float]]:
    """从 ffmpeg silencedetect 的 stderr 里解析出静音段。"""
    out: list[tuple[float, float]] = []
    cur = None
    for line in text.splitlines():
        m = _SIL_START.search(line)
        if m:
            cur = float(m.group(1))
        m = _SIL_END.search(line)
        if m and cur is not None:
            out.append((cur, float(m.group(1))))
            cur = None
    return out


def detect_silences(audio: Path, ffmpeg: str,
                    noise: str = NOISE, min_sil: float = MIN_SIL):
    r = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(audio), "-af",
         f"silencedetect=noise={noise}:d={min_sil}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return parse_silences(r.stderr)


def pick_pause(pauses, a_end, b_start):
    """选本句结尾之后的那段静音。

    Whisper 的 word.end 偏早，真实停顿通常在 a.end 之后 0~0.6s。
    优先取“起点落在 a.end 之后、b.start 附近”的第一段；找不到再退化为最近的一段。
    """
    # 首选：停顿起点在 a.end 之后（最多容 0.15s 误差）。
    # 同窗口里可能夹着句中的短停顿，按「时长 - 离 a.end 的距离」打分，长停顿优先。
    cands = [(a, b) for a, b in pauses
             if a_end - 0.15 <= a <= b_start + 0.25]
    if cands:
        return max(cands, key=lambda p: (p[1] - p[0]) - 0.5 * abs(p[0] - a_end))
    # 退路：离当前边界最近的一段；太远说明句间本来就没有停顿，交给中点切分
    t0 = (a_end + b_start) / 2
    cands = [(a, b) for a, b in pauses
             if b >= a_end - 0.80 and a <= b_start + 0.30]
    if not cands:
        return None

    def dist(p):
        a, b = p
        return 0.0 if a <= t0 <= b else min(abs(a - t0), abs(b - t0))

    best = min(cands, key=dist)
    return best if dist(best) <= 0.25 else None


def snap(t: dict, pauses) -> int:
    """起止都吸附（旧版全量修正用）。返回改动句数。"""
    before = [s["end"] for sec in t["sections"] for it in sec["items"]
              for s in it["sentences"]]
    for sec in t["sections"]:
        for it in sec["items"]:
            ss = it["sentences"]
            if not ss:
                continue
            cstart, cend = it["content"]["start"], it["content"]["end"]
            ss[0]["start"] = round(cstart, 2)
            ss[-1]["end"] = round(cend, 2)
            for a, b in zip(ss, ss[1:]):
                p = pick_pause(pauses, a["end"], b["start"])
                if p:
                    s, e = p
                    a["end"] = round(min(s + min(0.10, 0.35 * (e - s)), b["start"] + 0.25), 2)
                    b["start"] = round(max(e - min(0.08, 0.25 * (e - s)), a["end"] - 0.05), 2)
                else:
                    mid = (a["end"] + b["start"]) / 2
                    a["end"] = round(mid + 0.03, 2)
                    b["start"] = round(mid - 0.03, 2)
            # 兜底：保持单调、不越界
            for s in ss:
                s["start"] = round(max(cstart, min(s["start"], cend)), 2)
                s["end"] = round(max(s["start"] + 0.15, min(s["end"], cend)), 2)
            for a, b in zip(ss, ss[1:]):
                if b["start"] < a["start"]:
                    b["start"] = a["start"]
    after = [s["end"] for sec in t["sections"] for it in sec["items"]
             for s in it["sentences"]]
    return sum(1 for x, y in zip(before, after) if x != y)


def snap_ends(t: dict, pauses) -> int:
    """保守版：只把句尾吸附到真实停顿，句首一律不动。返回改动句数。

    句首偏早只会多播静音；句尾偏早会切掉尾音。切新音频与批量修旧卷都用这个版本，
    避免把句首拉进上一句（实测有卷会被拉前 5 秒）。
    """
    before = [s["end"] for sec in t["sections"] for it in sec["items"]
              for s in it["sentences"]]
    for sec in t["sections"]:
        for it in sec["items"]:
            ss = it["sentences"]
            if not ss:
                continue
            cend = it["content"]["end"]
            for k, s in enumerate(ss):
                e = s["end"]
                n = ss[k + 1]["start"] if k + 1 < len(ss) else cend
                cands = [(a, b) for a, b in pauses
                         if e - 0.10 <= a <= max(e + 0.80, n + 0.30)]
                if cands:
                    a, b = min(cands, key=lambda p: abs(p[0] - e))
                    new_e = a + min(0.10, 0.40 * (b - a))
                    new_e = min(new_e, n + 0.30)   # 最多和下句重叠 0.3s
                    new_e = max(new_e, e)          # 只往后延，不往回缩
                else:
                    new_e = min(e + 0.15, n + 0.15)
                s["end"] = round(new_e, 3)
            # 末句至少覆盖到正文终点
            ss[-1]["end"] = round(max(ss[-1]["end"], cend), 3)
            # 兜底：零时长/极短句至少给 0.25s
            for k, s in enumerate(ss):
                if s["end"] - s["start"] < 0.25:
                    nxt = ss[k + 1]["start"] if k + 1 < len(ss) else cend
                    s["end"] = round(min(max(s["start"] + 0.25, s["end"]), nxt + 0.20), 3)
    after = [s["end"] for sec in t["sections"] for it in sec["items"]
             for s in it["sentences"]]
    return sum(1 for x, y in zip(before, after) if x != y)
