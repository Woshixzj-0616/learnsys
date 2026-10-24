"""P3 Web 工作台后端：模块清单、静态页、设置读写/掩码、上传、多轮历史。"""
from __future__ import annotations

import base64
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.llm import config as agent_config
from learnsys.agent.events import AgentEvent
from learnsys.server import routes_agent
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}

PNG_1PX = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
           "/x8AAusB9Wl2nWQAAAAASUVORK5CYII=")


class WebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.data_root = root / "data"
        self.settings_file = root / "设置.json"
        self.db_path = root / "learning.db"

        conn = store.connect(self.db_path)
        conn.close()
        self._orig_connect = store.connect
        patches = [
            mock.patch.object(store, "connect",
                              side_effect=lambda path=None: self._orig_connect(path or self.db_path)),
            mock.patch.object(app_config, "DATA_ROOT", self.data_root),
            mock.patch.object(app_config, "SETTINGS_FILE", self.settings_file),
            mock.patch.object(app_config, "USER", {}),
            mock.patch.object(agent_config, "CLAUDE_SETTINGS", root / "无此文件.json"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

        self.app = create_app(token=TOKEN)
        self.client = TestClient(self.app)

    def test_modules_and_static_shell(self):
        result = self.client.get("/api/modules", headers=AUTH)
        self.assertEqual(result.status_code, 200)
        modules = result.json()["modules"]
        ids = {item["id"] for item in modules}
        self.assertGreaterEqual(len(modules), 10)
        self.assertIn("vocab", ids)
        self.assertEqual(len(ids), len(modules))
        self.assertEqual(modules[0]["id"], "today")
        self.assertEqual(modules[1]["id"], "ask")
        self.assertEqual(modules[-1]["id"], "plugins")

        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn("学习工作台", index.text)
        self.assertIn("/web/js/shell.js", index.text)
        self.assertEqual(self.client.get("/web/css/tokens.css").status_code, 200)

    def test_settings_masked_and_saved(self):
        initial = self.client.get("/api/settings", headers=AUTH).json()
        self.assertFalse(initial["agent"]["auth_token_set"])
        self.assertEqual(initial["agent"]["auth_token_mask"], "")
        self.assertGreaterEqual(len(initial["modules"]), 10)
        self.assertIn("vocab", initial["modules"])

        payload = {
            "agent": {"base_url": "https://example.test/anthropic",
                      "auth_token": "sk-test-123456",
                      "model": "deepseek-v4-pro"},
            "vision": {"base_url": "https://vision.test/v1",
                       "api_key": "vk-test-abcdef",
                       "model": "glm-4v-flash"},
            "hotkey": "Ctrl+Shift+F2",
            "modules": {"quiz": False},
        }
        saved = self.client.post("/api/settings", json=payload, headers=AUTH)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertIn("hotkey", saved.json()["restart_required"])

        raw = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(raw["agent"]["auth_token"], "sk-test-123456")
        self.assertEqual(raw["hotkey"], "Ctrl+Shift+F2")

        after = self.client.get("/api/settings", headers=AUTH).json()
        self.assertTrue(after["agent"]["auth_token_set"])
        self.assertEqual(after["agent"]["auth_token_mask"], "••••3456")
        self.assertEqual(after["agent"]["auth_token_source"], "file")
        self.assertNotIn("123456", json.dumps(after, ensure_ascii=False))
        self.assertFalse(after["modules"]["quiz"])
        self.assertTrue(after["modules"]["today"])

        # 留空密钥 = 不改
        again = self.client.post("/api/settings", json={
            "agent": {"auth_token": ""}, "vision": {"api_key": ""}}, headers=AUTH)
        self.assertEqual(again.status_code, 200)
        raw = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(raw["agent"]["auth_token"], "sk-test-123456")
        self.assertEqual(raw["vision"]["api_key"], "vk-test-abcdef")

    def test_settings_auto_route(self):
        saved = self.client.post("/api/settings", headers=AUTH, json={
            "agent": {"auto_route": "shadow",
                      "strong_model": " deepseek-v4-pro "}})
        self.assertEqual(saved.status_code, 200, saved.text)
        after = self.client.get("/api/settings", headers=AUTH).json()["agent"]
        self.assertEqual(after["auto_route"], "shadow")
        self.assertEqual(after["strong_model"], "deepseek-v4-pro")

        bad = self.client.post("/api/settings", headers=AUTH,
                               json={"agent": {"auto_route": "maybe"}})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("自动路由", bad.json()["detail"])

    def test_agent_route_stats_api(self):
        conn = store.connect(self.db_path)
        store.add_agent_run(
            conn, run_id="route-1", question="为什么并发会死锁",
            started_at=store.now(), trace=[{
                "kind": "route",
                "data": {"tier": "standard", "model": "deepseek-flash",
                         "auto": "shadow",
                         "recommended": {"tier": "deep", "model": "deepseek-v4-pro",
                                         "thinking": True,
                                         "reason": "复杂度 3：5 个难度词"}},
            }])
        conn.close()

        data = self.client.get("/api/agent/routes/stats?days=7", headers=AUTH).json()
        self.assertEqual(data["with_route"], 1)
        self.assertEqual(data["escalations"], 1)
        self.assertEqual(data["recommended_tiers"], {"deep": 1})

    def test_settings_reject_bad_hotkey(self):
        bad = self.client.post("/api/settings", json={"hotkey": "Q"},
                               headers=AUTH)
        self.assertEqual(bad.status_code, 400)
        self.assertIn("快捷键", bad.json()["detail"])

    def test_upload_image_and_doc(self):
        image = self.client.post("/api/upload", headers=AUTH, json={
            "name": "截图.png", "data": PNG_1PX, "kind": "image"})
        self.assertEqual(image.status_code, 200, image.text)
        path = pathlib.Path(image.json()["path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

        text = "这是一份测试文档，内容足够长，可以正常抽取文字。"
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        doc = self.client.post("/api/upload", headers=AUTH, json={
            "name": "讲义.txt", "data": encoded, "kind": "doc"})
        self.assertEqual(doc.status_code, 200, doc.text)
        self.assertEqual(doc.json()["text"], text)

        bad = self.client.post("/api/upload", headers=AUTH, json={
            "name": "坏文件.exe", "data": encoded, "kind": "auto"})
        self.assertEqual(bad.status_code, 400)

    def test_chat_passes_history(self):
        conn = store.connect()
        conv = store.create_conversation(conn, title="旧对话")
        store.add_message(conn, conv, "user", {"text": "第一问"})
        store.add_message(conn, conv, "assistant", {"text": "第一答"})
        conn.close()

        seen = {}

        def fake_run(request, cfg=None, abort=None, **_kwargs):
            seen["history"] = request.history
            yield AgentEvent("done", data={"text": "第二答", "thinking": "想一想"})

        with mock.patch.object(routes_agent.agent, "run", fake_run):
            response = self.client.post("/api/agent/chat", headers=AUTH, json={
                "message": "第二问", "conversation_id": conv})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["history"], [("第一问", "第一答")])

        detail = self.client.get(f"/api/conversations/{conv}", headers=AUTH).json()
        self.assertEqual(detail["messages"][-1]["content"]["thinking"], "想一想")

    def test_quickbar_bridge(self):
        from learnsys.server import runtime
        runtime.clear_ui()
        self.addCleanup(runtime.clear_ui)

        missing = self.client.post("/api/quickbar/show", headers=AUTH)
        self.assertEqual(missing.status_code, 503)
        self.assertIn("快捷栏没在运行", missing.json()["detail"])

        called = []
        runtime.register_ui(show_bar=lambda: called.append("show"),
                            pick=lambda: called.append("pick"))
        self.assertEqual(self.client.post("/api/quickbar/show", headers=AUTH).status_code, 200)
        self.assertEqual(self.client.post("/api/quickbar/pick", headers=AUTH).status_code, 200)
        self.assertEqual(called, ["show", "pick"])
        self.assertEqual(self.client.post("/api/quickbar/show").status_code, 403)

    def test_backup_endpoint(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        (self.data_root / "学习档案.md").write_text("测试", encoding="utf-8")
        result = self.client.post("/api/settings/backup", headers=AUTH)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(pathlib.Path(result.json()["path"]).exists())


if __name__ == "__main__":
    unittest.main()
