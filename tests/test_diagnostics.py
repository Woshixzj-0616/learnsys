"""静默异常留痕：写日志、轮转、日志本身失败也不抛。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import diagnostics
from learnsys.services import observability


class TestLogSwallow(unittest.TestCase):
    def test_writes_context_and_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            try:
                raise RuntimeError("写库失败")
            except RuntimeError as exc:
                diagnostics.log_swallow("测试写入", exc, data_root=root)
            text = (root / diagnostics.LOG_NAME).read_text(encoding="utf-8")
            self.assertIn("测试写入", text)
            self.assertIn("RuntimeError", text)
            self.assertIn("写库失败", text)

    def test_rotates_when_file_is_too_large(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            path = root / diagnostics.LOG_NAME
            path.write_text("x" * (diagnostics.MAX_BYTES + 1), encoding="utf-8")
            diagnostics.log_swallow("新错误", ValueError("新的"),
                                    data_root=root)
            self.assertTrue((root / "启动错误-上次.log").exists())
            text = path.read_text(encoding="utf-8")
            self.assertIn("新错误", text)
            self.assertNotIn("xxxx", text)

    def test_unwritable_log_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "不是目录").write_text("占位", encoding="utf-8")
            diagnostics.log_swallow("写不了", RuntimeError("x"),
                                    data_root=root / "不是目录")

    def test_observability_failures_are_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with mock.patch.object(observability.store, "connect",
                                   side_effect=RuntimeError("库打不开")), \
                 mock.patch.object(diagnostics.config, "DATA_ROOT", root):
                self.assertEqual(observability.start_run(surface="cet6"), 0)
                observability.finish_run(7, status="done", ms=10)
            text = (root / diagnostics.LOG_NAME).read_text(encoding="utf-8")
            self.assertIn("开始流水", text)
            self.assertIn("完成流水", text)
            self.assertIn("库打不开", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
