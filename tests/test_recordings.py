# -*- coding: utf-8 -*-
"""录像域：schema 加列、会话读写、转写正文、删除与旧库迁移。"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

from learnsys import config, store
from learnsys.core import db as core_db


class RecordingStoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_schema_has_video_columns(self):
        session_cols = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(sessions)").fetchall()}
        for name in ("kind", "title", "video_path", "video_bytes", "duration_ms",
                     "thumb_path", "slides_dir", "material_id",
                     "analysis_result_id"):
            self.assertIn(name, session_cols)
        frame_cols = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(frame_text)").fetchall()}
        self.assertIn("session_id", frame_cols)

    def test_recording_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = pathlib.Path(tmp) / "video.mp4"
            video.write_bytes(b"fake-video")
            self._roundtrip(video)

    def _roundtrip(self, video: pathlib.Path):
        sid = store.start_session(self.conn)
        self.conn.execute(
            "UPDATE sessions SET started_at = '2026-10-25 14:03:00' WHERE id = ?",
            (sid,))
        store.add_transcript(self.conn, sid, "2026-10-25 14:03:05",
                             "2026-10-25 14:03:20", "今天讲 TCP 三次握手")
        store.add_transcript(self.conn, sid, "2026-10-25 14:04:00",
                             "2026-10-25 14:04:10", "第二次握手是 SYN+ACK")
        store.update_video(
            self.conn, sid, video_path=str(video), video_bytes=video.stat().st_size,
            duration_ms=65000, thumb_path=str(video.parent / "thumb.jpg"),
            slides_dir=str(video.parent / "slides"))

        items = store.list_recordings(self.conn)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["transcripts"], 2)
        self.assertGreater(items[0]["chars"], 0)
        self.assertEqual(items[0]["title"], "10-25 14:03 录像")

        detail = store.get_recording(self.conn, sid)
        self.assertEqual(detail["duration"], 65.0)
        self.assertEqual(detail["video_url"], f"/media/recordings/{sid}/video.mp4")
        self.assertEqual([item["clock"] for item in detail["transcripts"]],
                         ["00:05", "01:00"])
        text = store.recording_transcript(self.conn, sid)
        self.assertIn("[00:05] 今天讲 TCP 三次握手", text)
        self.assertIn("[01:00] 第二次握手是 SYN+ACK", text)

    def test_transcript_cap_marks_truncation(self):
        sid = store.start_session(self.conn)
        store.add_transcript(self.conn, sid, store.now(), store.now(), "字" * 50)
        text = store.recording_transcript(self.conn, sid, cap=10)
        self.assertIn("已省略", text)
        self.assertLessEqual(len(text), 40)

    def test_delete_removes_rows_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            folder = root / "20261025-140300-7"
            folder.mkdir()
            video = folder / "video.mp4"
            video.write_bytes(b"fake")
            sid = store.start_session(self.conn)
            store.add_transcript(self.conn, sid, store.now(), store.now(), "内容")
            store.update_video(self.conn, sid, video_path=str(video),
                               slides_dir=str(folder / "slides"))
            with mock.patch.object(config, "VIDEO_DIR", root):
                result = store.delete_recording(self.conn, sid)
            self.assertTrue(result["ok"])
            self.assertTrue(result["removed_files"])
            self.assertFalse(folder.exists())
            self.assertIsNone(store.get_recording(self.conn, sid))
            self.assertEqual(self.conn.execute(
                "SELECT COUNT(*) FROM transcripts WHERE session_id = ?",
                (sid,)).fetchone()[0], 0)

    def test_delete_refuses_folder_outside_video_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "recordings"
            root.mkdir()
            outside = pathlib.Path(tmp) / "别动"
            outside.mkdir()
            video = outside / "video.mp4"
            video.write_bytes(b"fake")
            sid = store.start_session(self.conn)
            store.update_video(self.conn, sid, video_path=str(video))
            with mock.patch.object(config, "VIDEO_DIR", root):
                result = store.delete_recording(self.conn, sid)
            self.assertTrue(result["ok"])
            self.assertFalse(result["removed_files"])
            self.assertTrue(outside.exists(), "录像根目录外的文件不能删")


class RecordingMigrationTest(unittest.TestCase):
    def test_old_db_gets_video_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "old.db"
            conn = sqlite3.connect(str(path))
            conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, "
                         "started_at TEXT NOT NULL, ended_at TEXT)")
            conn.execute("CREATE TABLE frame_text (path TEXT PRIMARY KEY, "
                         "ts TEXT NOT NULL, text TEXT NOT NULL)")
            conn.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, "
                         "title TEXT, module TEXT, mode TEXT, summary TEXT, "
                         "started_at TEXT, updated_at TEXT)")
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
            conn.close()

            upgraded = core_db.connect(path)
            try:
                session_cols = {row[1] for row in upgraded.execute(
                    "PRAGMA table_info(sessions)").fetchall()}
                frame_cols = {row[1] for row in upgraded.execute(
                    "PRAGMA table_info(frame_text)").fetchall()}
                conversation_cols = {row[1] for row in upgraded.execute(
                    "PRAGMA table_info(conversations)").fetchall()}
                self.assertIn("video_path", session_cols)
                self.assertIn("session_id", frame_cols)
                self.assertIn("origin", conversation_cols)
                self.assertIn("recording_id", conversation_cols)
                version = upgraded.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(version, core_db.SCHEMA_VERSION)
            finally:
                upgraded.close()


if __name__ == "__main__":
    unittest.main()
