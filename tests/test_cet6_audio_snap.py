# -*- coding: utf-8 -*-
"""六级句尾吸附：纯函数行为 + 分割器接线。

背景：whisper 的 word.end 偏早（中位 0.19s），工作台按 start/end 精确截取会切尾音。
`cet6-src/audio_snap.py::snap_ends` 是唯一实现，这里锁住行为，防止以后改回直接用 word.end。
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP_PATH = ROOT / "cet6-src" / "audio_snap.py"
SPLIT_PATH = ROOT / "cet6-src" / "split_listening.py"

_spec = importlib.util.spec_from_file_location("cet6_audio_snap", SNAP_PATH)
audio_snap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audio_snap)


def make_timeline(points, content_end=None):
    """points: [(start, end), ...]；content_end 默认取末句 end。"""
    sentences = [
        {"i": i + 1, "start": float(a), "end": float(b), "en": f"s{i + 1}"}
        for i, (a, b) in enumerate(points)
    ]
    cend = float(content_end) if content_end is not None else points[-1][1]
    return {
        "sections": [{
            "name": "Section A",
            "items": [{
                "title": "Conversation 1",
                "content": {"start": points[0][0], "end": cend},
                "sentences": sentences,
            }],
        }],
    }


def ends(t):
    return [s["end"] for sec in t["sections"] for it in sec["items"]
            for s in it["sentences"]]


class ParseSilencesTest(unittest.TestCase):
    def test_parses_pairs_and_ignores_dangling_start(self):
        text = "\n".join([
            "[silencedetect @ 0x1] silence_start: 1.25",
            "[silencedetect @ 0x1] silence_end: 1.80 | silence_duration: 0.55",
            "[silencedetect @ 0x1] silence_start: 9.00",
            "unrelated line",
        ])
        self.assertEqual(audio_snap.parse_silences(text), [(1.25, 1.80)])

    def test_empty_text(self):
        self.assertEqual(audio_snap.parse_silences(""), [])


class SnapEndsTest(unittest.TestCase):
    def test_extends_tail_to_silence_edge(self):
        t = make_timeline([(1.0, 3.0), (5.0, 7.0)])
        changed = audio_snap.snap_ends(t, [(3.2, 3.5)])
        # 末句没有对应静音 → 走 0.15 尾垫；两句都被改。
        self.assertEqual(ends(t), [3.3, 7.15])
        self.assertEqual(changed, 2)

    def test_never_shrinks_past_end(self):
        t = make_timeline([(1.0, 3.0), (5.0, 7.0)])
        audio_snap.snap_ends(t, [(3.0, 3.4)])
        self.assertGreaterEqual(ends(t)[0], 3.0)

    def test_no_pause_falls_back_to_small_pad(self):
        t = make_timeline([(1.0, 3.0), (10.0, 12.0)])
        audio_snap.snap_ends(t, [])
        self.assertAlmostEqual(ends(t)[0], 3.15, places=3)

    def test_overlap_capped_at_next_start_plus_30(self):
        t = make_timeline([(1.0, 3.0), (3.05, 6.0)])
        audio_snap.snap_ends(t, [(3.4, 3.6)])
        self.assertAlmostEqual(ends(t)[0], 3.35, places=3)

    def test_last_sentence_covers_content_end(self):
        t = make_timeline([(1.0, 3.0)], content_end=3.4)
        audio_snap.snap_ends(t, [])
        self.assertAlmostEqual(ends(t)[0], 3.4, places=3)

    def test_too_short_sentence_gets_min_duration(self):
        t = make_timeline([(1.0, 3.0), (3.05, 3.10)], content_end=10.0)
        audio_snap.snap_ends(t, [])
        self.assertGreaterEqual(ends(t)[1] - 3.05, 0.25)

    def test_only_tail_moves_starts_untouched(self):
        t = make_timeline([(1.0, 3.0), (5.0, 7.0)])
        starts_before = [s["start"] for sec in t["sections"] for it in sec["items"]
                         for s in it["sentences"]]
        audio_snap.snap_ends(t, [(3.2, 3.5)])
        starts_after = [s["start"] for sec in t["sections"] for it in sec["items"]
                        for s in it["sentences"]]
        self.assertEqual(starts_before, starts_after)


class SplitterWiringTest(unittest.TestCase):
    def test_splitter_uses_shared_snap(self):
        text = SPLIT_PATH.read_text(encoding="utf-8")
        self.assertIn("from audio_snap import detect_silences, snap_ends", text)
        self.assertIn("snap_ends(paper, pauses)", text)
        self.assertIn('"--no-snap"', text)

    def test_splitter_does_not_build_ends_from_word_end_only(self):
        text = SPLIT_PATH.read_text(encoding="utf-8")
        # 句子构建处只允许写原始边界，收尾吸附必须在 write_outputs 统一做。
        self.assertIn('"end": round(sent[-1].end, 3)', text)


if __name__ == "__main__":
    unittest.main()
