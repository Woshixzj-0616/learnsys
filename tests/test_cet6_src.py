# -*- coding: utf-8 -*-
"""六级源码快照：关键文件在、音频/试卷没被误提交、本机源码没漂移。"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "cet6-src"
LOCAL = pathlib.Path(r"D:\cet6_tool")
AUDIO_SUFFIX = {".mp3", ".wav", ".m4a", ".aac", ".flac"}


class Cet6SourceSnapshotTest(unittest.TestCase):
    def test_key_sources_are_present(self):
        for rel in (
            "workbench_src/js/00-core.js",
            "workbench_src/js/04-mode.js",
            "workbench_src/js/56-dualwrite.js",
            "workbench_src/js/65-ask.js",
            "workbench_src/tests/test_ranges.mjs",
            "workbench_src/tests/test_dualwrite.mjs",
            "build_workbench.py",
            "split_listening.py",
            "校对/结构修复.json",
        ):
            self.assertTrue((SRC / rel).is_file(), f"缺少六级源码：{rel}")

    def test_no_audio_or_papers(self):
        offenders = []
        for path in SRC.rglob("*"):
            if path.is_dir() and path.name in ("试卷", "音频"):
                offenders.append(path)
            elif path.is_file() and path.suffix.lower() in AUDIO_SUFFIX:
                offenders.append(path)
        self.assertEqual(offenders, [], f"这些不该进仓库：{offenders[:5]}")

    def test_correction_patches_are_complete(self):
        patches = list((SRC / "校对").glob("*.json"))
        self.assertGreaterEqual(len(patches), 50)

    @unittest.skipUnless(LOCAL.is_dir(), "本机没有 D:\\cet6_tool，跳过漂移检查")
    def test_local_sources_are_not_ahead(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sync_cet6_src", ROOT / "tools" / "sync_cet6_src.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.check(), 0, "六级源码有改动还没同步进仓库")


if __name__ == "__main__":
    unittest.main()
