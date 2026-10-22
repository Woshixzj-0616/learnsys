"""启动链路：复用/起 8765、被占退 8766、打开学习工作台窗口。"""
from __future__ import annotations

import unittest
from unittest import mock

from learnsys.ask import app as app_mod
from learnsys.ask import workbench
from learnsys.ask.desktop import web_service


class _Bar:
    def __init__(self):
        self.messages = []

    def show_message(self, text):
        self.messages.append(text)


def _bare_app():
    obj = app_mod.AskApp.__new__(app_mod.AskApp)
    obj._web_server = None
    obj._web_port = 0
    obj._web_external = False
    obj.bar = _Bar()
    obj.warnings = []
    obj._warn = obj.warnings.append
    return obj


class StartWebTest(unittest.TestCase):
    def test_reuse_healthy_server(self):
        obj = _bare_app()
        with mock.patch.object(web_service, "_server_healthy", return_value=True), \
                mock.patch.object(web_service, "_server_has_ui", return_value=True):
            app_mod.AskApp.start_web(obj)
        self.assertEqual(obj._web_port, 8765)
        self.assertTrue(obj._web_external)
        self.assertIsNone(obj._web_server)

    def test_healthy_without_ui_is_not_reused(self):
        obj = _bare_app()
        with mock.patch.object(web_service, "_server_healthy",
                               side_effect=lambda port, timeout=0.5: port == 8765), \
                mock.patch.object(web_service, "_server_has_ui", return_value=False), \
                mock.patch("learnsys.server.app.port_free", return_value=True), \
                mock.patch("learnsys.server.app.serve_in_thread", return_value="server"):
            app_mod.AskApp.start_web(obj)
        self.assertEqual(obj._web_port, 8766)
        self.assertFalse(obj._web_external)

    def test_fallback_to_8766(self):
        obj = _bare_app()

        def free(port):
            return port == 8766

        with mock.patch.object(web_service, "_server_healthy", return_value=False), \
                mock.patch("learnsys.server.app.port_free", side_effect=free), \
                mock.patch("learnsys.server.app.serve_in_thread", return_value="server") as serve:
            app_mod.AskApp.start_web(obj)
        self.assertEqual(obj._web_port, 8766)
        self.assertEqual(obj._web_server, "server")
        serve.assert_called_once_with(8766)

    def test_both_ports_busy_warns(self):
        obj = _bare_app()
        with mock.patch.object(web_service, "_server_healthy", return_value=False), \
                mock.patch("learnsys.server.app.port_free", return_value=False):
            app_mod.AskApp.start_web(obj)
        self.assertEqual(obj._web_port, 0)
        self.assertTrue(obj.warnings)
        self.assertIn("端口", obj.warnings[0])

    def test_open_web_uses_app_window(self):
        obj = _bare_app()
        obj._web_port = 8765
        with mock.patch.object(workbench, "open_or_focus", return_value="msedge.exe") as opened:
            app_mod.AskApp.open_web(obj)
        opened.assert_called_once_with("http://127.0.0.1:8765/")
        self.assertIn("学习工作台", obj.bar.messages[-1])


if __name__ == "__main__":
    unittest.main()
