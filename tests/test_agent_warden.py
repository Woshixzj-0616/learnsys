# -*- coding: utf-8 -*-
"""P32 验收闸门：快照、差集、四种检查、契约归一。全程零模型调用。"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from learnsys.services.agents import warden


def _git(root: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True)


class _Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def write(self, rel: str, text: str) -> pathlib.Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def read_contract(self, **kwargs) -> dict:
        return warden.build_default_contract("read", self.root, **kwargs)

    def write_contract(self, **kwargs) -> dict:
        return warden.build_default_contract("write", self.root, **kwargs)


class SnapshotTest(_Temp):
    def test_walk_records_and_excludes(self):
        self.write("a.txt", "甲")
        self.write("node_modules/pkg/x.js", "x")
        self.write("build-2.0/y.txt", "y")
        snap = warden.snapshot(self.root)
        self.assertEqual(snap["kind"], "walk")
        self.assertIn("a.txt", snap["entries"])
        self.assertNotIn("node_modules/pkg/x.js", snap["entries"])
        self.assertNotIn("build-2.0/y.txt", snap["entries"])

    def test_walk_truncates(self):
        for index in range(5):
            self.write(f"f{index}.txt", "x")
        snap = warden.snapshot(self.root, max_files=3)
        self.assertTrue(snap["truncated"])
        self.assertEqual(len(snap["entries"]), 3)

    def test_exclude_hides_system_files(self):
        self.write("a.txt", "甲")
        self.write("数据/learning.db-wal", "wal")
        exclude = [self.root / "数据" / "learning.db-wal"]
        before = warden.snapshot(self.root, exclude=exclude)
        self.write("数据/learning.db-wal", "wal 变了")
        after = warden.snapshot(self.root, exclude=exclude)
        self.assertNotIn("数据/learning.db-wal", before["entries"])
        self.assertEqual(warden.diff_snapshots(before, after)["changed"], [])

    def test_exclude_directory(self):
        self.write("学习档案/agents/0001.md", "结果")
        snap = warden.snapshot(self.root, exclude=[self.root / "学习档案"])
        self.assertNotIn("学习档案/agents/0001.md", snap["entries"])

    def test_missing_workspace_raises(self):
        with self.assertRaises(RuntimeError):
            warden.snapshot(self.root / "不存在")

    def test_diff_detects_add_modify_delete(self):
        before = warden.snapshot(self.root)
        self.write("new.txt", "新文件")
        self.write("gone.txt", "马上删")
        after = warden.snapshot(self.root)
        changes = warden.diff_snapshots(before, after)
        self.assertIn("new.txt", changes["changed"])
        self.assertIn("gone.txt", changes["changed"])

        # 改内容（长度不同，保证 size 变化）
        before2 = warden.snapshot(self.root)
        (self.root / "new.txt").write_text("新文件，改长了", encoding="utf-8")
        after2 = warden.snapshot(self.root)
        self.assertIn("new.txt", warden.diff_snapshots(before2, after2)["changed"])

        # 删除
        (self.root / "new.txt").unlink()
        after3 = warden.snapshot(self.root)
        self.assertIn("new.txt", warden.diff_snapshots(after2, after3)["changed"])

    def test_git_snapshot_ignores_preexisting_changes(self):
        try:
            _git(self.root, "init", "-q")
            _git(self.root, "config", "user.email", "t@example.com")
            _git(self.root, "config", "user.name", "t")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("本机没有可用的 git")
        self.write("tracked.txt", "原始")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-q", "-m", "初始")
        # 用户自己先改一个文件，再派活
        self.write("tracked.txt", "用户自己的改动")
        before = warden.snapshot(self.root)
        self.assertEqual(before["kind"], "git")
        # agent 没动任何东西
        after = warden.snapshot(self.root)
        changes = warden.diff_snapshots(before, after)
        self.assertEqual(changes["changed"], [])

    def test_git_commit_detected(self):
        try:
            _git(self.root, "init", "-q")
            _git(self.root, "config", "user.email", "t@example.com")
            _git(self.root, "config", "user.name", "t")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("本机没有可用的 git")
        self.write("a.txt", "a")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-q", "-m", "初始")
        before = warden.snapshot(self.root)
        self.write("b.txt", "b")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-q", "-m", "agent 提交了")
        changes = warden.diff_snapshots(before, warden.snapshot(self.root))
        self.assertTrue(changes["commit_detected"])


class ContractTest(_Temp):
    def test_default_read_contract(self):
        contract = self.read_contract()
        checks = [item["check"] for item in contract["acceptance"]]
        self.assertEqual(checks, ["no_workspace_change", "within_scope"])
        self.assertFalse(contract["scope"]["allow_write"])
        self.assertEqual(contract["scope"]["max_files"], 0)

    def test_default_write_contract(self):
        contract = self.write_contract()
        checks = [item["check"] for item in contract["acceptance"]]
        self.assertEqual(checks, ["within_scope"])
        self.assertEqual(contract["scope"]["max_files"], warden.DEFAULT_MAX_FILES)

    def test_normalize_empty_uses_default(self):
        contract, error = warden.normalize_contract({}, "read", self.root)
        self.assertEqual(error, "")
        self.assertTrue(contract["auto"])

    def test_normalize_keeps_auto_flag_after_roundtrip(self):
        # 路由先归一、落库，runner 再从库里读出来归一一次：必须仍然算「自动」。
        contract = self.read_contract()
        again, error = warden.normalize_contract(
            json.dumps(contract, ensure_ascii=False), "read", self.root)
        self.assertEqual(error, "")
        self.assertTrue(again["auto"])

    def test_normalize_unknown_check(self):
        _, error = warden.normalize_contract(
            {"scope": {"roots": [str(self.root)]},
             "acceptance": [{"check": "看起来像对的就是对的"}]}, "read", self.root)
        self.assertIn("未知", error)

    def test_normalize_bad_roots(self):
        _, error = warden.normalize_contract(
            {"scope": {"roots": []}, "acceptance": []}, "read", self.root)
        self.assertIn("roots", error)

    def test_normalize_non_object(self):
        _, error = warden.normalize_contract(["不是对象"], "read", self.root)
        self.assertIn("对象", error)


class VerifyReadOnlyTest(_Temp):
    def test_no_change_passes(self):
        self.write("a.txt", "甲")
        before = warden.snapshot(self.root)
        verdict = warden.verify(self.read_contract(), self.root, before)
        self.assertEqual(verdict["state"], "passed")
        self.assertEqual(verdict["changes"]["count"], 0)

    def test_read_only_change_fails(self):
        self.write("a.txt", "甲")
        before = warden.snapshot(self.root)
        self.write("a.txt", "甲甲甲")
        verdict = warden.verify(self.read_contract(), self.root, before)
        self.assertEqual(verdict["state"], "failed")
        self.assertIn("a.txt", verdict["changes"]["changed"])
        self.assertIn("改动了工作区", verdict["items"][0]["detail"])

    def test_commit_detected_fails_read_only(self):
        before = warden.snapshot(self.root)
        after = {"kind": "git", "head": "bbb", "entries": {}, "truncated": False}
        before = {"kind": "git", "head": "aaa", "entries": {}, "truncated": False}
        changes = warden.diff_snapshots(before, after)
        self.assertTrue(changes["commit_detected"])


class VerifyWriteTest(_Temp):
    def test_within_scope_passes(self):
        contract = self.write_contract()
        before = warden.snapshot(self.root)
        self.write("a.py", "print(1)")
        self.write("b.py", "print(2)")
        verdict = warden.verify(contract, self.root, before)
        self.assertEqual(verdict["state"], "passed")
        self.assertEqual(verdict["changes"]["count"], 2)

    def test_max_files_exceeded(self):
        contract = warden.build_default_contract("write", self.root, max_files=1)
        before = warden.snapshot(self.root)
        self.write("a.py", "1")
        self.write("b.py", "2")
        verdict = warden.verify(contract, self.root, before)
        self.assertEqual(verdict["state"], "failed")
        self.assertIn("超过上限", verdict["items"][0]["detail"])

    def test_outside_roots_fails(self):
        contract = warden.build_default_contract("write", self.root, max_files=10)
        contract["scope"]["roots"] = [str(self.root / "allowed")]
        (self.root / "allowed").mkdir()
        before = warden.snapshot(self.root)
        self.write("outside.txt", "越界")
        verdict = warden.verify(contract, self.root, before)
        self.assertEqual(verdict["state"], "failed")
        self.assertIn("outside.txt", verdict["items"][0]["detail"])

    def test_truncated_snapshot_is_error(self):
        contract = self.write_contract()
        before = {"kind": "walk", "head": "", "entries": {}, "truncated": False}
        original = warden.snapshot
        warden.snapshot = lambda *a, **k: {"kind": "walk", "head": "",
                                           "entries": {}, "truncated": True}
        try:
            verdict = warden.verify(contract, self.root, before)
        finally:
            warden.snapshot = original
        self.assertEqual(verdict["state"], "error")
        self.assertIn("截断", verdict["summary"])


class CheckTest(_Temp):
    def _verify(self, contract):
        return warden.verify(contract, self.root, warden.snapshot(self.root))

    def test_file_nonempty(self):
        contract = {"scope": {"roots": [str(self.root)], "max_files": 0},
                    "acceptance": [{"id": "f", "check": "file_nonempty",
                                    "args": {"path": "a.txt"}}]}
        self.write("a.txt", "有内容")
        self.assertEqual(self._verify(contract)["state"], "passed")
        self.write("a.txt", "")
        self.assertEqual(self._verify(contract)["state"], "failed")

    def test_file_nonempty_missing(self):
        contract = {"scope": {"roots": [str(self.root)], "max_files": 0},
                    "acceptance": [{"id": "f", "check": "file_nonempty",
                                    "args": {"path": "没有.txt"}}]}
        self.assertEqual(self._verify(contract)["state"], "failed")

    def test_file_nonempty_path_escape(self):
        contract = {"scope": {"roots": [str(self.root)], "max_files": 0},
                    "acceptance": [{"id": "f", "check": "file_nonempty",
                                    "args": {"path": "../../etc/passwd"}}]}
        verdict = self._verify(contract)
        self.assertEqual(verdict["state"], "failed")
        self.assertIn("越界", verdict["items"][0]["actual"])

    def test_command_zero(self):
        contract = {"scope": {"roots": [str(self.root)], "max_files": 0},
                    "acceptance": [{"id": "c", "check": "command_zero",
                                    "args": {"cmd": [sys.executable, "-c", "print(1)"]}}]}
        self.assertEqual(self._verify(contract)["state"], "passed")

    def test_command_nonzero(self):
        contract = {"scope": {"roots": [str(self.root)], "max_files": 0},
                    "acceptance": [{"id": "c", "check": "command_zero",
                                    "args": {"cmd": [sys.executable, "-c", "raise SystemExit(1)"]}}]}
        self.assertEqual(self._verify(contract)["state"], "failed")

    def test_command_not_allowlisted(self):
        contract = {"scope": {"roots": [str(self.root)], "max_files": 0},
                    "acceptance": [{"id": "c", "check": "command_zero",
                                    "args": {"cmd": ["curl", "http://example.com"]}}]}
        verdict = self._verify(contract)
        self.assertEqual(verdict["state"], "failed")
        self.assertIn("白名单", verdict["items"][0]["expected"])

    def test_command_bad_args(self):
        contract = {"scope": {"roots": [str(self.root)], "max_files": 0},
                    "acceptance": [{"id": "c", "check": "command_zero",
                                    "args": {"cmd": "rm -rf"}}]}
        verdict = self._verify(contract)
        self.assertEqual(verdict["state"], "failed")
        self.assertIn("字符串数组", verdict["items"][0]["detail"])


class StateTest(_Temp):
    def test_no_contract_is_skipped(self):
        verdict = warden.verify(None, self.root, warden.snapshot(self.root))
        self.assertEqual(verdict["state"], "skipped")

    def test_empty_acceptance_is_error(self):
        contract = {"scope": {"roots": [str(self.root)]}, "acceptance": []}
        verdict = warden.verify(contract, self.root, warden.snapshot(self.root))
        self.assertEqual(verdict["state"], "error")

    def test_unknown_check_in_verify_is_failed_not_pass(self):
        contract = {"scope": {"roots": [str(self.root)]},
                    "acceptance": [{"id": "x", "check": "不存在的检查"}]}
        verdict = warden.verify(contract, self.root, warden.snapshot(self.root))
        self.assertEqual(verdict["state"], "failed")

    def test_check_exception_does_not_pass(self):
        contract = {"scope": {"roots": [str(self.root)]},
                    "acceptance": [{"id": "x", "check": "within_scope"}]}
        original = warden._CHECK_FUNCS["within_scope"]

        def boom(_item, _ctx):
            raise RuntimeError("检查自己炸了")

        warden._CHECK_FUNCS["within_scope"] = boom
        try:
            verdict = warden.verify(contract, self.root, warden.snapshot(self.root))
        finally:
            warden._CHECK_FUNCS["within_scope"] = original
        self.assertEqual(verdict["state"], "failed")
        self.assertIn("检查异常", verdict["items"][0]["detail"])

    def test_bad_before_snapshot_is_error_not_raise(self):
        contract = self.read_contract()
        verdict = warden.verify(contract, self.root, before="不是快照")
        self.assertEqual(verdict["state"], "error")

    def test_missing_workspace_is_error(self):
        contract = self.read_contract()
        before = warden.snapshot(self.root)
        verdict = warden.verify(contract, self.root / "没了", before)
        self.assertEqual(verdict["state"], "error")
        self.assertIn("失败", verdict["summary"])

    def test_dumps_truncates_but_keeps_state(self):
        long_path = "很长的路径" * 20
        verdict = {"state": "failed", "summary": "1/2 通过",
                   "changes": {"changed": [f"{long_path}{index}" for index in range(500)]},
                   "items": [{"id": str(index), "detail": long_path}
                             for index in range(100)]}
        text = warden.dumps(verdict)
        self.assertLessEqual(len(text), warden.MAX_VERDICT_JSON)
        data = json.loads(text)          # 必须是合法 JSON
        self.assertEqual(data["state"], "failed")
        self.assertTrue(data["changes"]["truncated"])

    def test_dumps_roundtrip(self):
        verdict = {"state": "passed", "items": []}
        self.assertEqual(warden.loads(warden.dumps(verdict))["state"], "passed")
        self.assertEqual(warden.loads("坏 json"), {})


if __name__ == "__main__":
    unittest.main()
