"""部署脚本：目录换入/回滚、健康检查筛选、守护开关顺序（不真起进程）。"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest import mock

from tools import deploy


def make_layout(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    prod = root / "dist" / "学习工作台"
    build = root / "dist-build" / "学习工作台"
    prod.mkdir(parents=True)
    build.mkdir(parents=True)
    (prod / "old.txt").write_text("旧版", encoding="utf-8")
    (prod / deploy.EXE_NAME).write_text("旧 exe", encoding="utf-8")
    (build / deploy.EXE_NAME).write_text("新 exe", encoding="utf-8")
    (build / "new.txt").write_text("新版", encoding="utf-8")
    return prod, build


class TestPaths(unittest.TestCase):
    def test_unique_path_avoids_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "备份"
            path.mkdir()
            self.assertEqual(deploy.unique_path(path).name, "备份-2")
            (path.parent / "备份-2").mkdir()
            self.assertEqual(deploy.unique_path(path).name, "备份-3")

    def test_swap_in_moves_old_and_copies_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            prod, build = make_layout(root)
            backup = root / "备份"
            deploy.swap_in(build, prod, backup)
            self.assertTrue((prod / "new.txt").is_file())
            self.assertTrue((backup / "old.txt").is_file())
            self.assertTrue((build / deploy.EXE_NAME).is_file(), "构建目录应保留")

    def test_swap_in_failure_restores_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            prod, build = make_layout(root)
            backup = root / "备份"
            with mock.patch.object(deploy.shutil, "copytree",
                                   side_effect=OSError("磁盘满")):
                with self.assertRaises(OSError):
                    deploy.swap_in(build, prod, backup)
            self.assertTrue((prod / "old.txt").is_file())
            self.assertFalse(backup.exists())

    def test_latest_backup_picks_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            prod = root / "学习工作台"
            prod.mkdir()
            old = root / "学习工作台-2.20.0-backup"
            new = root / "学习工作台-2.20.1-backup"
            old.mkdir()
            new.mkdir()
            os.utime(old, (1000, 1000))
            os.utime(new, (2000, 2000))
            self.assertEqual(deploy.latest_backup(prod), new)


class TestHealth(unittest.TestCase):
    def test_wait_healthy_requires_version_and_quickbar(self):
        replies = [
            {"ok": True, "version": "2.20.0", "quickbar": True},   # 版本不对
            {"ok": True, "version": "2.20.1", "quickbar": False},  # 没有快捷栏
            {"ok": True, "version": "2.20.1", "quickbar": True},   # 通过
        ]

        def fake(port, timeout=0.8):
            return replies.pop(0) if replies else None

        with mock.patch.object(deploy, "health", side_effect=fake):
            port, data = deploy.wait_healthy(
                expect_version="2.20.1", timeout=3)
        self.assertEqual(port, deploy.PORTS[0])
        self.assertEqual(data["version"], "2.20.1")


class TestRunDeploy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.prod, self.build = make_layout(self.root)
        self.info = {
            "build": self.build, "prod": self.prod, "backup": None,
            "live": None, "guard": "Ready", "expect_version": "2.20.1",
            "timeout": 1,
        }
        self.guard_calls = []
        patches = [
            mock.patch.object(deploy, "set_guard",
                              side_effect=lambda value: self.guard_calls.append(value)),
            mock.patch.object(deploy, "stop_backend", return_value=[123]),
            mock.patch.object(deploy, "wait_down"),
            mock.patch.object(deploy, "start_backend", return_value=object()),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_success_swaps_and_restores_guard(self):
        with mock.patch.object(deploy, "wait_healthy",
                               return_value=(8765, {"version": "2.20.1",
                                                    "quickbar": True})):
            code = deploy.run_deploy(self.info, rollback=False)
        self.assertEqual(code, 0)
        self.assertTrue((self.prod / "new.txt").is_file())
        backups = list((self.root / "dist").glob("学习工作台-*-backup"))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "old.txt").is_file())
        self.assertEqual(self.guard_calls, [False, True])

    def test_failure_after_swap_rolls_back(self):
        replies = [deploy.DeployError("健康检查超时"),
                   (8765, {"version": "2.20.0", "quickbar": True})]
        with mock.patch.object(deploy, "wait_healthy", side_effect=replies):
            code = deploy.run_deploy(self.info, rollback=False)
        self.assertEqual(code, 1)
        self.assertTrue((self.prod / "old.txt").is_file())
        self.assertFalse((self.prod / "new.txt").exists())
        self.assertTrue(list((self.root / "dist").glob("学习工作台-失败-*")))
        self.assertEqual(self.guard_calls, [False, True])

    def test_failure_before_swap_keeps_prod_and_restarts_old(self):
        with mock.patch.object(deploy, "stop_backend",
                               side_effect=deploy.DeployError("停不掉")), \
             mock.patch.object(deploy, "wait_healthy",
                               return_value=(8765, {"version": "2.20.0",
                                                    "quickbar": True})):
            code = deploy.run_deploy(self.info, rollback=False)
        self.assertEqual(code, 1)
        self.assertTrue((self.prod / "old.txt").is_file())
        self.assertFalse(list((self.root / "dist").glob("学习工作台-*-backup")))
        self.assertEqual(self.guard_calls, [False, True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
