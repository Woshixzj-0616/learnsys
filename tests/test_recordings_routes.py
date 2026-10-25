# -*- coding: utf-8 -*-
"""录像接口：列表/详情、MP4 Range、缩略图、幻灯片、存资料、打开文件夹、删除。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config, store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class RecordingsRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.db_path = root / "learning.db"
        self.video_root = root / "录像"
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
        (self.folder / "video.mp4").write_bytes(b"fake-mp4-bytes")
        (self.folder / "thumb.jpg").write_bytes(b"fake-jpg")
        (self.folder / "幻灯片" / "slide_0001.jpg").write_bytes(b"slide-jpg")

        conn = store.connect()
        sid = store.start_session(conn)
        conn.execute(
            "UPDATE sessions SET started_at = '2026-10-25 14:03:00' WHERE id = ?",
            (sid,))
        store.add_transcript(conn, sid, "2026-10-25 14:03:05",
                             "2026-10-25 14:03:10", "第一段内容")
        store.update_video(
            conn, sid, video_path=str(self.folder / "video.mp4"),
            video_bytes=(self.folder / "video.mp4").stat().st_size,
            duration_ms=62000, thumb_path=str(self.folder / "thumb.jpg"),
            slides_dir=str(self.folder / "幻灯片"))
        conn.close()
        self.sid = sid
        self.client = TestClient(create_app(token=TOKEN))

    def test_list_and_detail(self):
        self.assertEqual(self.client.get("/api/recordings").status_code, 403)
        listed = self.client.get("/api/recordings", headers=AUTH)
        self.assertEqual(listed.status_code, 200)
        data = listed.json()
        self.assertEqual(data["totals"]["count"], 1)
        self.assertEqual(data["items"][0]["id"], self.sid)
        self.assertEqual(data["items"][0]["transcripts"], 1)

        detail = self.client.get(f"/api/recordings/{self.sid}", headers=AUTH)
        self.assertEqual(detail.status_code, 200)
        item = detail.json()
        self.assertEqual(item["duration"], 62.0)
        self.assertEqual(item["transcripts"][0]["clock"], "00:05")
        self.assertEqual(item["slides"][0]["name"], "slide_0001.jpg")
        self.assertTrue(item["video_url"].endswith("/video.mp4"))

    def test_media_serves_without_token_and_supports_range(self):
        status = self.client.get(f"/media/recordings/{self.sid}/video.mp4")
        self.assertEqual(status.status_code, 200)
        ranged = self.client.get(
            f"/media/recordings/{self.sid}/video.mp4",
            headers={"Range": "bytes=0-3"})
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(ranged.content, b"fake")
        self.assertEqual(
            self.client.get(f"/media/recordings/{self.sid}/thumb.jpg").status_code, 200)
        slide = self.client.get(
            f"/media/recordings/{self.sid}/slides/slide_0001.jpg")
        self.assertEqual(slide.status_code, 200)
        self.assertEqual(slide.content, b"slide-jpg")

    def test_material_is_idempotent(self):
        first = self.client.post(
            f"/api/recordings/{self.sid}/material", headers=AUTH)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["created"])
        second = self.client.post(
            f"/api/recordings/{self.sid}/material", headers=AUTH)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["created"])
        self.assertEqual(first.json()["item"]["id"], second.json()["item"]["id"])

    def test_open_folder_uses_validated_helper(self):
        with mock.patch("learnsys.server.routes_recordings.ops.open_path",
                        return_value="已打开文件夹") as opened:
            response = self.client.post(
                f"/api/recordings/{self.sid}/open-folder", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "已打开文件夹")
        opened.assert_called_once()

    def test_analyze_and_poll_and_cancel(self):
        with mock.patch(
                "learnsys.server.routes_recordings.video_analysis.submit",
                return_value={"id": 7, "status": "pending", "cached": False}) as submit:
            response = self.client.post(
                f"/api/recordings/{self.sid}/analyze?force=true", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 7)
        submit.assert_called_once_with(self.sid, force=True)

        done = {"id": 7, "status": "done", "content": {"markdown": "## 分析"}}
        with mock.patch(
                "learnsys.server.routes_recordings.video_analysis.latest",
                return_value=done):
            polled = self.client.get(
                f"/api/recordings/{self.sid}/analysis", headers=AUTH)
        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.json()["analysis"]["status"], "done")

        with mock.patch(
                "learnsys.server.routes_recordings.video_analysis.latest",
                return_value=done), mock.patch(
                "learnsys.server.routes_recordings.video_analysis.cancel",
                return_value=True):
            canceled = self.client.post(
                f"/api/recordings/{self.sid}/analysis/cancel", headers=AUTH)
        self.assertEqual(canceled.status_code, 200)
        self.assertTrue(canceled.json()["ok"])

    def test_analyze_unknown_recording_is_404(self):
        with mock.patch(
                "learnsys.server.routes_recordings.video_analysis.submit",
                side_effect=ValueError("没有这段录像")):
            response = self.client.post(
                "/api/recordings/99999/analyze", headers=AUTH)
        self.assertEqual(response.status_code, 404)

    def test_delete_removes_files_and_rows(self):
        response = self.client.delete(f"/api/recordings/{self.sid}", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(self.folder.exists())
        self.assertEqual(
            self.client.get(f"/api/recordings/{self.sid}", headers=AUTH).status_code, 404)


if __name__ == "__main__":
    unittest.main()
