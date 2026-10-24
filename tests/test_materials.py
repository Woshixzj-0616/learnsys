# -*- coding: utf-8 -*-
"""资料库：落库、检索排序、上传抽取、笔记、回收站、挂载问一问、Agent 工具。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.agent import config as agent_config
from learnsys.agent import tools
from learnsys.agent.events import AgentEvent
from learnsys.materials import search as material_search
from learnsys.modules import load_registry
from learnsys.server import routes_agent
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class TestMaterialStore(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_note_crud_and_counts(self):
        item_id, created = store.add_material(
            self.conn, title="子网笔记", kind="note", source="note",
            body="# 子网\n\n/27 可用 30 个。", tags="子网")
        self.assertTrue(created)
        item = store.get_material(self.conn, item_id)
        self.assertEqual(item["kind"], "note")
        self.assertIn("30 个", item["body"])
        self.assertEqual(store.material_counts(self.conn)["active"], 1)

        updated = store.update_material(
            self.conn, item_id, title="子网速算笔记", body="# 新内容")
        self.assertEqual(updated["title"], "子网速算笔记")
        self.assertEqual(updated["chars"], len("# 新内容"))

    def test_dedupe_by_sha(self):
        first, created = store.add_material(
            self.conn, title="a.pdf", kind="pdf", source="upload",
            body="正文", sha256="abc")
        second, again = store.add_material(
            self.conn, title="b.pdf", kind="pdf", source="upload",
            body="正文", sha256="abc")
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(first, second)
        self.assertEqual(len(store.list_materials(self.conn)), 1)

    def test_add_event(self):
        event_id = store.add_event(self.conn, "materials", "open", "课件",
                                   {"material_id": 3})
        row = self.conn.execute(
            "SELECT module, kind, title FROM events WHERE id = ?", (event_id,)).fetchone()
        self.assertEqual(row, ("materials", "open", "课件"))

    def test_status_and_delete(self):
        item_id, _ = store.add_material(self.conn, title="临时", body="内容")
        self.assertTrue(store.set_material_status(self.conn, item_id, "trashed"))
        self.assertEqual(len(store.list_materials(self.conn, status="trashed")), 1)
        self.assertTrue(store.delete_material_row(self.conn, item_id))
        self.assertIsNone(store.get_material(self.conn, item_id))


class TestDocumentExtraction(unittest.TestCase):
    def test_pdf_pages_use_form_feed(self):
        import pymupdf
        from learnsys.services import study

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "课件.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), "page one subnet /27")
            page = doc.new_page()
            page.insert_text((72, 72), "page two routing")
            doc.save(str(path))
            doc.close()
            result = study.extract_document(str(path))
        self.assertEqual(result["kind"], "pdf")
        self.assertEqual(result["pages"], 2)
        self.assertIn("\f", result["text"], "PDF 分页要留换页符，检索才能算页码")

    def test_txt_passthrough(self):
        from learnsys.services import study

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "笔记.txt"
            path.write_text("子网划分", encoding="utf-8")
            result = study.extract_document(str(path))
        self.assertEqual(result["kind"], "txt")
        self.assertEqual(result["pages"], 0)
        self.assertEqual(result["text"], "子网划分")


class TestMaterialSearch(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        store.add_material(
            self.conn, title="子网划分课件", kind="pdf", source="upload",
            body="第一页\f/27 的可用主机数是 30 个；网络地址和广播地址要减掉。")
        store.add_material(
            self.conn, title="路由笔记", kind="note", source="note",
            body="OSPF 邻居卡在 ExStart 时先看 MTU。")

    def tearDown(self):
        self.conn.close()

    def test_entity_hit_and_page(self):
        hits = material_search.search(self.conn, "子网 可用主机", limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["material_id"], 1)
        self.assertEqual(hits[0]["page"], 2, "换页符前的命中在第 2 页")
        self.assertIn("30 个", hits[0]["snippet"])

    def test_unrelated_query_returns_empty(self):
        self.assertEqual(material_search.search(self.conn, "完全无关的词组"), [])

    def test_page_at_ppt_markers(self):
        text = "--- 第 1 页 ---\n甲\n\n--- 第 3 页 ---\n乙"
        self.assertEqual(material_search.page_at(text, text.index("乙")), 3)


class MaterialApiTest(unittest.TestCase):
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

    def _conn(self):
        return self._orig_connect(self.db_path)

    def _note(self, title="测试笔记"):
        return self.client.post("/api/materials/note", headers=AUTH, json={
            "title": title, "body": "# 内容\n\n子网划分。", "tags": "子网",
        }).json()["item"]

    def test_upload_raw_and_dedupe(self):
        content = "子网划分：/27 的可用主机数是 30 个。".encode("utf-8")
        first = self.client.post(
            "/api/materials/upload?name=课件.txt", headers=AUTH, content=content).json()
        self.assertTrue(first["created"])
        self.assertEqual(first["item"]["kind"], "txt")
        self.assertIn("30 个", first["item"]["preview"])

        second = self.client.post(
            "/api/materials/upload?name=另一份.txt", headers=AUTH, content=content).json()
        self.assertFalse(second["created"])
        self.assertEqual(first["item"]["id"], second["item"]["id"])

    def test_upload_pdf_keeps_pages(self):
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "first page: subnet mask")
        page = doc.new_page()
        page.insert_text((72, 72), "second page: usable hosts 30")
        blob = doc.tobytes()
        doc.close()

        result = self.client.post(
            "/api/materials/upload?name=课件.pdf", headers=AUTH, content=blob).json()
        self.assertTrue(result["created"])
        self.assertEqual(result["item"]["kind"], "pdf")
        self.assertEqual(result["item"]["pages"], 2)

        found = self.client.get("/api/materials?q=usable hosts", headers=AUTH).json()
        self.assertEqual(found["items"][0]["page"], 2)

    def test_upload_rejects_scanned_and_bad_suffix(self):
        bad = self.client.post(
            "/api/materials/upload?name=恶意.exe", headers=AUTH, content=b"x")
        self.assertEqual(bad.status_code, 400)
        empty = self.client.post(
            "/api/materials/upload?name=扫描.txt", headers=AUTH,
            content="短".encode("utf-8"))
        self.assertEqual(empty.status_code, 400)
        self.assertIn("OCR", empty.json()["detail"])

    def test_note_update_export_and_list(self):
        item = self._note()
        updated = self.client.post(f"/api/materials/{item['id']}", headers=AUTH,
                                   json={"body": "# 新标题\n\n更新后的正文"}).json()
        self.assertIn("更新后的正文", updated["item"]["body"])

        listing = self.client.get("/api/materials?status=active", headers=AUTH).json()
        self.assertEqual(len(listing["items"]), 1)
        self.assertEqual(listing["counts"]["active"], 1)

        exported = self.client.get(f"/api/materials/{item['id']}/export", headers=AUTH)
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/markdown", exported.headers["content-type"])
        self.assertIn("更新后的正文", exported.content.decode("utf-8"))

    def test_search_api_returns_snippet_and_page(self):
        self.client.post(
            "/api/materials/upload?name=子网.txt", headers=AUTH,
            content="第一页讲子网划分：\f/27 可用主机 30 个，网络地址和广播地址要减掉。".encode("utf-8"))
        data = self.client.get("/api/materials?q=可用主机", headers=AUTH).json()
        self.assertTrue(data["items"])
        self.assertEqual(data["items"][0]["page"], 2)
        self.assertIn("30 个", data["items"][0]["snippet"])

    def test_trash_restore_permanent_delete(self):
        item = self._note()
        self.client.post(f"/api/materials/{item['id']}/trash", headers=AUTH)
        trashed = self.client.get("/api/materials?status=trashed", headers=AUTH).json()
        self.assertEqual(len(trashed["items"]), 1)

        restored = self.client.post(
            f"/api/materials/{item['id']}/restore", headers=AUTH).json()
        self.assertEqual(restored["item"]["status"], "active")

        self.client.post(f"/api/materials/{item['id']}/trash", headers=AUTH)
        deleted = self.client.delete(f"/api/materials/{item['id']}", headers=AUTH)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/materials", headers=AUTH)
                         .json()["items"], [])

    def test_material_quiz_prompt(self):
        item = self._note()
        result = self.client.get(
            f"/api/materials/{item['id']}/quiz-prompt", headers=AUTH).json()
        self.assertEqual(result["material"]["id"], item["id"])
        prompt = result["prompt"]
        self.assertIn(item["title"], prompt)
        self.assertIn(f"资料 id={item['id']}", prompt)
        self.assertIn("一次只出一题", prompt)
        self.assertIn("read_material", prompt)

    def test_material_events_in_study_today(self):
        self.client.post("/api/events", headers=AUTH, json={
            "module": "materials", "kind": "open", "title": "子网课件",
            "meta": {"material_id": 1},
        })
        self.client.post("/api/events", headers=AUTH, json={
            "module": "materials", "kind": "quiz", "title": "子网课件",
            "meta": {"material_id": 1},
        })
        data = self.client.get("/api/study/today", headers=AUTH).json()
        self.assertEqual(data["stats"]["materials"], 2)
        self.assertTrue(any(line.startswith("资料：子网课件") for line in data["summary_lines"]))

    def test_material_attached_to_ask(self):
        item = self._note()
        conn = self._conn()
        try:
            store.update_material(conn, item["id"],
                                  body="这份资料的唯一标记：CIDR-ONLY-MARK")
        finally:
            conn.close()
        seen = {}

        def fake_run(request, cfg=None, abort=None, **_kwargs):
            seen["name"] = request.attachment_name
            seen["text"] = request.attachment_text
            yield AgentEvent("done", data={"text": "收到"})

        with mock.patch.object(routes_agent.agent, "run", fake_run):
            response = self.client.post("/api/agent/chat", headers=AUTH, json={
                "message": "这份资料讲什么？", "material_id": item["id"],
                "internal": True,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["name"], "测试笔记")
        self.assertIn("CIDR-ONLY-MARK", seen["text"])

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/materials").status_code, 403)
        self.assertEqual(self.client.post("/api/materials/note", json={}).status_code, 403)


class TestMaterialQuizPrompt(unittest.TestCase):
    def test_builder_mentions_material_and_tools(self):
        from learnsys.services import study

        prompt = study.build_material_quiz_question({
            "id": 7, "title": "子网课件", "body": "第一页\f/27 可用主机 30 个。",
            "chars": 24, "pages": 2,
        })
        self.assertIn("《子网课件》", prompt)
        self.assertIn("资料 id=7", prompt)
        self.assertIn("--- 第 2 页 ---", prompt)
        self.assertIn("read_material(material_id=7)", prompt)
        self.assertIn("save_wrongbook", prompt)

    def test_builder_truncates_long_body(self):
        from learnsys.services import study

        prompt = study.build_material_quiz_question({
            "id": 8, "title": "长资料", "body": "字" * 500, "chars": 500,
        }, cap=100)
        self.assertIn("正文只给了前 100 字", prompt)


class TestMaterialTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        self.item_id, _ = store.add_material(
            conn, title="子网课件", kind="pdf", source="upload",
            body="第一页\f/27 可用主机 30 个；第二页讲路由汇总。")
        self.long_id, _ = store.add_material(
            conn, title="长资料", kind="txt", source="upload",
            body="第一页\f" + "用" * 1200)
        conn.close()
        self.ctx = tools.ToolContext(
            data_root=pathlib.Path(self.tmp.name), db_path=self.db_path, mode="explain")

    def test_search_materials(self):
        text = tools.search_materials("可用主机", ctx=self.ctx)
        self.assertIn("子网课件", text)
        self.assertIn("第 2 页", text)
        self.assertIn("30 个", text)

    def test_read_material_offset(self):
        text = tools.read_material(self.long_id, offset=3, length=500, ctx=self.ctx)
        self.assertIn("共", text)
        self.assertIn("offset=", text)

    def test_schema_present(self):
        names = [tool["name"] for tool in tools.schemas_for("explain")]
        self.assertIn("search_materials", names)
        self.assertIn("read_material", names)


class TestMaterialPlugin(unittest.TestCase):
    def test_plugin_ready_and_files(self):
        modules = load_registry()["modules"]
        module = next(item for item in modules if item["id"] == "materials")
        self.assertEqual(module["status"], "ready")
        self.assertTrue(module["home"])
        root = pathlib.Path(__file__).resolve().parents[1]
        self.assertTrue((root / "web" / module["entry"]).is_file())
        self.assertTrue((root / "web" / module["script"]).is_file())

    def test_sw_precaches_materials(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        text = (root / "web" / "sw.js").read_text(encoding="utf-8")
        self.assertIn("/web/pages/materials.html", text)
        self.assertIn("/web/js/pages/materials.js", text)

    def test_material_quiz_entry_exists(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        materials = (root / "web" / "js" / "pages" / "materials.js").read_text(encoding="utf-8")
        quiz = (root / "web" / "js" / "pages" / "quiz.js").read_text(encoding="utf-8")
        self.assertIn("用这份资料出题", materials)
        self.assertIn("quiz?material=", materials)
        self.assertIn("/quiz-prompt", quiz)
        self.assertIn("material_id", quiz)
        self.assertIn("attach_material: false", quiz)


if __name__ == "__main__":
    unittest.main(verbosity=2)
