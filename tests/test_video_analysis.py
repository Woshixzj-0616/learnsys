# -*- coding: utf-8 -*-
"""录像分析：转写 + 幻灯片 OCR → Markdown、analysis.md、资料、缓存、取消。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import config, store
from learnsys.agent.events import AgentEvent
from learnsys.services import results, video_analysis

TOKEN = "test-token"
MARKDOWN = """## 这段课讲了什么
TCP 三次握手。

## 时间线提纲
- 00:05 讲了 SYN
- 01:00 讲了 SYN+ACK

## 关键要点
- 客户端先发 SYN

## 术语表
| 术语 | 解释 |
| --- | --- |
| SYN | 同步序号 |

## 没讲清 / 值得追问的地方
- 第三次握手的超时
"""


class FakeCfg:
    model = "fake-model"


class VideoAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db_path = self.root / "learning.db"
        self.video_root = self.root / "录像"
        store.connect(self.db_path).close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.config_patch = mock.patch.object(config, "VIDEO_DIR", self.video_root)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

        self.folder = self.video_root / "20261025-140300-1"
        (self.folder / "幻灯片").mkdir(parents=True)
        (self.folder / "video.mp4").write_bytes(b"fake-mp4")
        (self.folder / "thumb.jpg").write_bytes(b"fake-jpg")
        for name in ("slide_0001_140305.jpg", "slide_0002_140320.jpg"):
            (self.folder / "幻灯片" / name).write_bytes(b"slide")

        conn = store.connect()
        self.sid = store.start_session(conn)
        conn.execute(
            "UPDATE sessions SET started_at = '2026-10-25 14:03:00', "
            "ended_at = '2026-10-25 14:05:00' WHERE id = ?", (self.sid,))
        store.add_transcript(conn, self.sid, "2026-10-25 14:03:05",
                             "2026-10-25 14:03:10", "今天讲 TCP 三次握手")
        store.update_video(
            conn, self.sid, video_path=str(self.folder / "video.mp4"),
            video_bytes=(self.folder / "video.mp4").stat().st_size,
            duration_ms=120000, thumb_path=str(self.folder / "thumb.jpg"),
            slides_dir=str(self.folder / "幻灯片"))
        transcript = store.recording_transcript(conn, self.sid)
        slides = store.recording_slides(conn, self.sid)
        self.digest = video_analysis.context_hash(self.sid, transcript, slides)
        conn.close()

        self.seen = {}
        self.ocr_patch = mock.patch.object(
            video_analysis, "ocr_image", side_effect=self._fake_ocr)
        self.ocr_patch.start()
        self.addCleanup(self.ocr_patch.stop)
        self.cfg_patch = mock.patch.object(
            video_analysis, "_analysis_cfg", return_value=FakeCfg())
        self.cfg_patch.start()
        self.addCleanup(self.cfg_patch.stop)

    def _fake_ocr(self, path):
        return f"幻灯片文字 {pathlib.Path(path).name}"

    def _fake_run(self, request, cfg=None, abort=None, **_kwargs):
        self.seen["prompt"] = request.message
        yield AgentEvent("done", data={
            "text": MARKDOWN,
            "usage": {"input_tokens": 12, "output_tokens": 34}})

    def _make_result(self, *, digest=None):
        conn = store.connect()
        try:
            result_id, created = results.create(
                conn, **self._key(digest), model="fake-model", input_json="{}")
            return result_id, created
        finally:
            conn.close()

    def _key(self, digest=None):
        return dict(kind=video_analysis.ANALYSIS_KIND, target_type="recording",
                    target_id=str(self.sid), scope="recording",
                    context_hash=digest or self.digest,
                    prompt_version=video_analysis.PROMPT_VERSION)

    def test_run_job_writes_markdown_material_and_ocr(self):
        result_id, created = self._make_result()
        self.assertTrue(created)
        with mock.patch("learnsys.services.video_analysis.agent.run", self._fake_run):
            video_analysis.run_job(result_id, self.sid)
        conn = store.connect()
        try:
            row = results.get(conn, result_id)
            self.assertEqual(row["status"], "done")
            content = json.loads(row["content_json"])
            self.assertIn("## 这段课讲了什么", content["markdown"])
            self.assertGreater(content["material_id"], 0)
            material = store.get_material(conn, content["material_id"], with_body=True)
            self.assertEqual(material["source"], "video")
            self.assertIn("TCP 三次握手", material["body"])
            session = store.get_recording(conn, self.sid)
            self.assertEqual(session["analysis_result_id"], result_id)
            self.assertEqual(session["material_id"], content["material_id"])
            frames = conn.execute(
                "SELECT ts, text FROM frame_text WHERE session_id = ? ORDER BY ts",
                (self.sid,)).fetchall()
            self.assertEqual(len(frames), 2)
            self.assertEqual(frames[0][0], "2026-10-25 14:03:05")
        finally:
            conn.close()
        self.assertTrue((self.folder / "analysis.md").exists())
        self.assertIn("TCP 三次握手", self.seen["prompt"])

    def test_second_submit_hits_cache(self):
        with mock.patch.object(video_analysis, "_ensure_worker"), \
                mock.patch.object(video_analysis._QUEUE, "put") as put:
            first = video_analysis.submit(self.sid)
            second = video_analysis.submit(self.sid)
        self.assertEqual(first["status"], "pending")
        self.assertFalse(first["cached"])
        self.assertEqual(second["id"], first["id"])
        self.assertTrue(second["cached"])
        put.assert_called_once()

    def test_force_creates_new_result(self):
        with mock.patch.object(video_analysis, "_ensure_worker"), \
                mock.patch.object(video_analysis._QUEUE, "put"):
            first = video_analysis.submit(self.sid)
            forced = video_analysis.submit(self.sid, force=True)
        self.assertNotEqual(first["id"], forced["id"])

    def test_empty_recording_reports_error(self):
        conn = store.connect()
        conn.execute("DELETE FROM transcripts WHERE session_id = ?", (self.sid,))
        conn.execute("UPDATE sessions SET slides_dir = '' WHERE id = ?", (self.sid,))
        conn.commit()
        conn.close()
        result_id, _created = self._make_result(
            digest=video_analysis.context_hash(self.sid, "", []))
        with mock.patch("learnsys.services.video_analysis.agent.run", self._fake_run):
            video_analysis.run_job(result_id, self.sid)
        conn = store.connect()
        try:
            row = results.get(conn, result_id)
            self.assertEqual(row["status"], "error")
            self.assertIn("没有转写也没有幻灯片", row["error"])
        finally:
            conn.close()

    def test_cancel_running_result(self):
        result_id, _created = self._make_result()
        self.assertTrue(video_analysis.cancel(result_id))
        conn = store.connect()
        try:
            self.assertEqual(results.get(conn, result_id)["status"], "canceled")
        finally:
            conn.close()
        self.assertFalse(video_analysis.cancel(result_id))


if __name__ == "__main__":
    unittest.main()
