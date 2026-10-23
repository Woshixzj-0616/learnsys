# -*- coding: utf-8 -*-
"""P20.2：工作台浏览器——URL/域名纯函数、CDP 解析、进程管理、存储、接口、Agent 工具。"""
from __future__ import annotations

import datetime
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.agent import loop, tools
from learnsys.agent.config import AgentConfig
from learnsys.agent.provider_anthropic import ProviderEvent, ProviderResult, ToolCall
from learnsys.browser import cdp, urls
from learnsys.browser.manager import BrowserManager, launch_args
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}

SETTINGS = {
    "enabled": True,
    "record": True,
    "exclude_domains": [],
    "history_days": 30,
    "close_on_exit": True,
}


def make_cfg(root: pathlib.Path) -> AgentConfig:
    return AgentConfig(
        base_url="http://127.0.0.1:9/v1", auth_token="test-token",
        model="test-model", fast_model="test-fast", max_tokens=1024,
        thinking=False, vision_base_url="", vision_api_key="",
        vision_model="glm-4v-flash", data_root=root,
        profile_path=root / "学习档案.md")


class FakeProc:
    def __init__(self, pid=4321):
        self.pid = pid
        self.terminated = False
        self.killed = False
        self._code = None

    def poll(self):
        return self._code

    def terminate(self):
        self.terminated = True
        self._code = 0

    def kill(self):
        self.killed = True
        self._code = -9

    def wait(self, timeout=None):
        return self._code


class FakePopen:
    def __init__(self, *args, **kwargs):
        self.args = args[0] if args else []
        self.proc = FakeProc()
        self.called = 0

    def __call__(self, *args, **kwargs):
        self.called += 1
        self.args = args[0] if args else []
        return self.proc


class UrlTest(unittest.TestCase):
    def test_http_https_pass(self):
        self.assertEqual(urls.normalize_url("https://example.com/a?b=1"),
                         "https://example.com/a?b=1")
        self.assertEqual(urls.normalize_url("http://example.com"), "http://example.com")

    def test_bare_domain_gets_https(self):
        self.assertEqual(urls.normalize_url("example.com"), "https://example.com")

    def test_bad_schemes_rejected(self):
        for raw in ("file:///C:/a.txt", "javascript:alert(1)", "data:text/html,x",
                    "ftp://example.com", "ms-settings:display"):
            with self.assertRaises(ValueError, msg=raw):
                urls.normalize_url(raw)

    def test_userinfo_rejected(self):
        with self.assertRaises(ValueError):
            urls.normalize_url("https://user:pass@example.com/")

    def test_too_long_and_space_rejected(self):
        with self.assertRaises(ValueError):
            urls.normalize_url("https://example.com/" + "a" * 2048)
        with self.assertRaises(ValueError):
            urls.normalize_url("https://example.com/a b")

    def test_domain_of_and_suffix_exclusion(self):
        self.assertEqual(urls.domain_of("https://Sub.Example.COM/x"), "sub.example.com")
        self.assertTrue(urls.is_excluded("a.example.com", ["example.com"]))
        self.assertTrue(urls.is_excluded("example.com", ["EXAMPLE.com"]))
        self.assertFalse(urls.is_excluded("notexample.com", ["example.com"]))

    def test_loopback(self):
        self.assertTrue(urls.is_loopback("localhost"))
        self.assertTrue(urls.is_loopback("127.0.0.1"))
        self.assertTrue(urls.is_loopback("app.localhost"))
        self.assertFalse(urls.is_loopback("example.com"))


class CdpParseTest(unittest.TestCase):
    def test_parse_pages_filters_and_skips_bad(self):
        payload = [
            {"type": "page", "id": "a", "url": "https://a.com", "title": "A"},
            {"type": "service_worker", "id": "s", "url": "https://s.com"},
            {"type": "page", "id": "", "url": "https://x.com"},
            {"type": "page", "id": "b", "url": ""},
            "不是对象",
        ]
        self.assertEqual(cdp.parse_pages(payload),
                         [{"id": "a", "url": "https://a.com", "title": "A"}])

    def test_parse_pages_bad_json_shape(self):
        self.assertEqual(cdp.parse_pages(None), [])
        self.assertEqual(cdp.parse_pages({"a": 1}), [])

    def test_read_devtools_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = pathlib.Path(tmp)
            (profile / "DevToolsActivePort").write_text("9222\n/devtools/browser/x\n",
                                                        encoding="utf-8")
            self.assertEqual(cdp.read_devtools_port(profile), 9222)
            (profile / "DevToolsActivePort").write_text("broken", encoding="utf-8")
            self.assertIsNone(cdp.read_devtools_port(profile))
            (profile / "DevToolsActivePort").unlink()
            self.assertIsNone(cdp.read_devtools_port(profile))


class LaunchArgsTest(unittest.TestCase):
    def test_required_flags(self):
        args = launch_args(pathlib.Path(r"D:\数据\浏览器配置"),
                           pathlib.Path(r"D:\数据\浏览器下载"), r"C:\Edge\msedge.exe")
        joined = " ".join(args)
        self.assertIn(r"--user-data-dir=D:\数据\浏览器配置", joined)
        self.assertIn("--remote-debugging-port=0", args)
        self.assertIn("--disable-sync", args)
        self.assertIn("--disable-extensions", args)
        self.assertNotIn("--app=", joined)
        self.assertNotIn("--headless", joined)


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.popen = FakePopen()
        self.manager = BrowserManager(data_root=self.root,
                                      browser_path=r"C:\Edge\msedge.exe",
                                      popen=self.popen)

    def _settings(self, **changes):
        value = dict(SETTINGS)
        value.update(changes)
        patcher = mock.patch("learnsys.browser.manager.config.browser_settings",
                             return_value=value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def test_disabled_does_not_start(self):
        self._settings(enabled=False)
        status = self.manager.launch()
        self.assertFalse(status["running"])
        self.assertEqual(self.popen.called, 0)
        self.assertIn("关闭", status["message"])

    def test_launch_timeout_gives_chinese_error(self):
        self._settings()
        with mock.patch("learnsys.browser.manager.cdp.read_devtools_port",
                        return_value=None), \
             mock.patch("learnsys.browser.manager.cdp.version_ok", return_value=False), \
             mock.patch("learnsys.browser.manager.LAUNCH_WAIT_SECONDS", 0.15):
            status = self.manager.launch()
        self.assertFalse(status["running"])
        self.assertIn("8 秒", status["message"])
        self.assertTrue(self.popen.proc.terminated)

    def test_launch_starts_poller_and_status(self):
        self._settings()
        # 第一次探测（接管检查）没有实例；随后启动，轮询才看到端口。
        with mock.patch("learnsys.browser.manager.cdp.read_devtools_port",
                        side_effect=[None, 9222]), \
             mock.patch("learnsys.browser.manager.cdp.version_ok", return_value=True), \
             mock.patch.object(self.manager, "_start_polling") as start:
            status = self.manager.launch()
        self.assertTrue(status["running"])
        start.assert_called_once()
        self.assertIn("--remote-debugging-port=0", self.popen.args)

    def test_adopts_running_instance_after_restart(self):
        self._settings()
        with mock.patch("learnsys.browser.manager.cdp.read_devtools_port",
                        return_value=9222), \
             mock.patch("learnsys.browser.manager.cdp.version_ok", return_value=True), \
             mock.patch.object(self.manager, "_start_polling"):
            status = self.manager.launch()
        self.assertEqual(self.popen.called, 0)
        self.assertTrue(status["running"])

    def test_existing_instance_is_reused(self):
        self._settings()
        self.manager._port = 9222
        with mock.patch("learnsys.browser.manager.cdp.version_ok", return_value=True):
            status = self.manager.launch()
        self.assertEqual(self.popen.called, 0)
        self.assertTrue(status["running"])

    def test_alive_uses_port_even_if_launcher_exited(self):
        self._settings()
        self.manager._port = 9222
        proc = FakeProc()
        proc._code = 0                    # 单例转发：launcher 退出了，浏览器还活着
        self.manager._proc = proc
        with mock.patch("learnsys.browser.manager.cdp.version_ok", return_value=True):
            self.assertTrue(self.manager.status()["running"])

    def test_close_adopted_instance_finds_pid_on_port(self):
        self._settings()
        self.manager._port = 9222
        self.manager._proc = None
        with mock.patch("learnsys.browser.manager._pid_on_port", return_value=5555), \
             mock.patch.object(self.manager, "_owns_pid", return_value=True), \
             mock.patch("learnsys.browser.manager.subprocess.run") as run:
            self.manager.close(force=True)
        self.assertTrue(any(call.args[0][:2] == ["taskkill", "/PID"]
                            for call in run.call_args_list))

    def test_close_only_kills_own_pid(self):
        self._settings()
        self.manager._proc = self.popen.proc
        self.manager._port = 9222
        with mock.patch.object(self.manager, "_owns_pid", return_value=False):
            self.manager.close(force=True)
        self.assertFalse(self.popen.proc.terminated)

        proc = FakeProc()
        self.manager._proc = proc
        with mock.patch.object(self.manager, "_owns_pid", return_value=True):
            self.manager.close(force=True)
        self.assertTrue(proc.terminated)

    def test_close_on_exit_false_keeps_browser(self):
        self._settings(close_on_exit=False)
        proc = FakeProc()
        self.manager._proc = proc
        self.manager.shutdown()
        self.assertFalse(proc.terminated)

    def test_record_pages_dedupes_and_filters(self):
        self._settings(exclude_domains=["secret.com"])
        conn = store.connect(self.root / "learning.db")
        try:
            pages = [
                {"id": "t1", "url": "https://example.com/a", "title": "A"},
                {"id": "t1", "url": "https://example.com/a", "title": "A"},
                {"id": "t2", "url": "https://secret.com/x", "title": "S"},
                {"id": "t3", "url": "http://127.0.0.1:8765/", "title": "本机"},
                {"id": "t4", "url": "file:///C:/a.txt", "title": "本地文件"},
                {"id": "t5", "url": "https://example.com/b", "title": "B"},
            ]
            self.manager._record_pages(conn, pages)
            self.manager._record_pages(conn, pages)
            rows = store.list_browser_events(conn, limit=50, days=0)
        finally:
            conn.close()
        self.assertEqual([row["url"] for row in rows],
                         ["https://example.com/b", "https://example.com/a"])

    def test_record_false_writes_nothing(self):
        self._settings(record=False)
        conn = store.connect(self.root / "learning.db")
        try:
            self.manager._record_pages(
                conn, [{"id": "t1", "url": "https://example.com/a", "title": "A"}])
            rows = store.list_browser_events(conn, limit=10, days=0)
        finally:
            conn.close()
        self.assertEqual(rows, [])

    def test_pause_then_resume_does_not_backfill(self):
        conn = store.connect(self.root / "learning.db")
        page = {"id": "t1", "url": "https://example.com/secret", "title": "私密"}
        try:
            self._settings(record=False)
            self.manager._record_pages(conn, [page])
            self._settings(record=True)
            self.manager._record_pages(conn, [page])
            self.assertEqual(store.list_browser_events(conn, limit=10, days=0), [])
            changed = dict(page, url="https://example.com/other")
            self.manager._record_pages(conn, [changed])
            self.assertEqual(len(store.list_browser_events(conn, limit=10, days=0)), 1)
        finally:
            conn.close()

    def test_open_url_validates_and_reuses(self):
        self._settings()
        self.manager._port = 9222
        with mock.patch("learnsys.browser.manager.cdp.version_ok", return_value=True), \
             mock.patch("learnsys.browser.manager.cdp.new_tab") as new_tab:
            result = self.manager.open_url("example.com")
        self.assertTrue(result["ok"])
        new_tab.assert_called_once_with(9222, "https://example.com")
        with self.assertRaises(ValueError):
            self.manager.open_url("file:///C:/a.txt")

    def test_open_url_disabled(self):
        self._settings(enabled=False)
        result = self.manager.open_url("https://example.com")
        self.assertFalse(result["ok"])
        self.assertIn("关闭", result["message"])


class BrowserStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(pathlib.Path(self.tmp.name) / "learning.db")
        self.addCleanup(self.conn.close)

    def test_dedupe_and_query(self):
        self.assertIsNotNone(store.add_browser_event(
            self.conn, tab_id="a", url="https://a.com/1", title="一", domain="a.com"))
        self.assertIsNone(store.add_browser_event(
            self.conn, tab_id="a", url="https://a.com/1", title="一", domain="a.com"))
        self.assertIsNotNone(store.add_browser_event(
            self.conn, tab_id="a", url="https://a.com/1", title="标题变了",
            domain="a.com"))
        store.add_browser_event(self.conn, tab_id="b", url="https://b.com/",
                                title="B", domain="b.com")
        self.assertEqual(len(store.list_browser_events(self.conn, limit=10, days=0)), 3)
        only_a = store.list_browser_events(self.conn, limit=10, days=0, domain="a.com")
        self.assertEqual(len(only_a), 2)
        self.assertEqual(only_a[0]["title"], "标题变了")

    def test_days_clear_and_cleanup(self):
        old = (datetime.datetime.now() - datetime.timedelta(days=40)).strftime(
            "%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO browser_events (ts, tab_id, url, title, domain) "
            "VALUES (?, 'old', 'https://old.com', '旧', 'old.com')", (old,))
        self.conn.commit()
        store.add_browser_event(self.conn, tab_id="new", url="https://new.com",
                                title="新", domain="new.com")
        self.assertEqual(len(store.list_browser_events(self.conn, limit=10, days=7)), 1)
        self.assertEqual(store.cleanup_browser_events(self.conn, 30), 1)
        self.assertEqual(store.clear_browser_events(self.conn), 1)
        self.assertEqual(store.list_browser_events(self.conn, limit=10, days=0), [])


class FakeManager:
    def __init__(self):
        self.opened = []
        self.history_args = {}
        self.recording = []

    def launch(self):
        return {"running": False, "enabled": True, "record": True,
                "paused": False, "current": None, "tabs": [],
                "message": "没找到 Edge 或 Chrome"}

    def open_url(self, url):
        normalized = urls.normalize_url(url)
        self.opened.append(normalized)
        return {"ok": True, "message": f"已打开：{normalized}", "url": normalized}

    def status(self):
        return {"running": True, "enabled": True, "record": True,
                "paused": False, "current": None, "tabs": [], "message": "运行中"}

    def history(self, *, limit=20, days=7, domain=""):
        self.history_args = {"limit": limit, "days": days, "domain": domain}
        return [{"id": 1, "ts": "2026-10-23 10:00:00", "tab_id": "t",
                 "url": "https://example.com", "title": "示例",
                 "domain": "example.com"}]

    def clear_history(self):
        return 2

    def set_recording(self, enabled):
        self.recording.append(bool(enabled))
        return self.status()

    def close(self, *, force=True):
        return self.status()


class BrowserApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake = FakeManager()
        patcher = mock.patch("learnsys.server.routes_browser.get_manager",
                             return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/browser/status").status_code, 403)
        self.assertEqual(self.client.post("/api/browser/launch").status_code, 403)

    def test_invalid_url_400_and_not_opened(self):
        res = self.client.post("/api/browser/open", headers=AUTH,
                               json={"url": "file:///C:/a.txt"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("http", res.json()["detail"])
        self.assertEqual(self.fake.opened, [])

    def test_open_ok(self):
        res = self.client.post("/api/browser/open", headers=AUTH,
                               json={"url": "example.com"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.fake.opened, ["https://example.com"])

    def test_history_limit_clamped(self):
        res = self.client.get("/api/browser/history?limit=500&days=999", headers=AUTH)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.fake.history_args["limit"], 100)
        self.assertEqual(self.fake.history_args["days"], 365)
        self.assertEqual(res.json()["count"], 1)

    def test_recording_and_clear(self):
        res = self.client.post("/api/browser/recording", headers=AUTH,
                               json={"enabled": False})
        self.assertTrue(res.json()["ok"])
        self.assertEqual(self.fake.recording, [False])
        cleared = self.client.delete("/api/browser/history", headers=AUTH).json()
        self.assertEqual(cleared["cleared"], 2)


class AgentBrowserToolsTest(unittest.TestCase):
    def test_open_url_needs_confirmation(self):
        self.assertIn("open_url", tools.CONFIRM_TOOLS)
        self.assertNotIn("open_url", tools.WRITE_TOOLS)
        self.assertIn("https://example.com", tools.write_summary(
            "open_url", {"url": "https://example.com"}))

    def test_schemas_skip_quiz(self):
        explain = {schema["name"] for schema in tools.schemas_for("explain")}
        quiz = {schema["name"] for schema in tools.schemas_for("quiz")}
        for name in ("open_url", "browser_status", "browser_history"):
            self.assertIn(name, explain)
            self.assertNotIn(name, quiz)

    def test_denied_open_does_not_call_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            fake_manager = FakeManager()
            with mock.patch("learnsys.agent.tools.system_tools.get_manager",
                            return_value=fake_manager):
                provider = ScriptProvider(
                    ProviderResult(
                        text="我来打开。",
                        tool_calls=[ToolCall("c1", "open_url",
                                             {"url": "https://example.com"})],
                        content_blocks=[{"type": "tool_use", "id": "c1",
                                         "name": "open_url",
                                         "input": {"url": "https://example.com"}}],
                        stop_reason="tool_use"),
                    ProviderResult(text="没有打开。", stop_reason="end_turn"),
                )
                events = list(loop.run(
                    loop.AgentRequest("打开 example.com"), provider=provider,
                    cfg=make_cfg(root), confirm=lambda *args: False))
            self.assertEqual(fake_manager.opened, [])
            tool_end = [event for event in events if event.kind == "tool_end"][0]
            self.assertTrue(tool_end.data["denied"])
            self.assertIn("没有执行", events[-1].data["text"])

    def test_history_limit_capped_at_50(self):
        fake_manager = FakeManager()
        with mock.patch("learnsys.agent.tools.system_tools.get_manager",
                        return_value=fake_manager):
            text = tools.browser_history(999, 7)
        self.assertEqual(fake_manager.history_args["limit"], 50)
        self.assertIn("example.com", text)

    def test_status_hides_current_when_paused(self):
        fake_manager = FakeManager()
        fake_manager.status = lambda: {
            "running": True, "paused": True, "current": {"url": "https://secret.com"},
            "message": "运行中"}
        with mock.patch("learnsys.agent.tools.system_tools.get_manager",
                        return_value=fake_manager):
            text = tools.browser_status()
        self.assertIn("暂停", text)
        self.assertNotIn("secret.com", text)


class ScriptProvider:
    def __init__(self, *results):
        self.results = list(results)

    def stream_messages(self, cfg, system, messages, tools, *, abort=None,
                        response_sink=None):
        result = self.results.pop(0) if self.results else ProviderResult(
            text="", stop_reason="end_turn")
        if result.text:
            yield ProviderEvent("text", result.text)
        yield ProviderEvent("done", result=result)


if __name__ == "__main__":
    unittest.main()
