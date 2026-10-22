# -*- coding: utf-8 -*-
"""错题本：统一表、旧收藏迁移、复习节奏、测验自动收题、导出与页面。"""
from __future__ import annotations

import datetime
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.agent import config as agent_config
from learnsys.agent import tools
from learnsys.ask import study
from learnsys.core import db as core_db
from learnsys.modules import load_registry
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


def _today() -> datetime.date:
    return datetime.date.today()


def _shift(conn, item_id: int, days: int, *, last_review: str = "") -> None:
    """把一条错题的收录日 / 上次复习日往回挪，模拟时间过去。"""
    stamp = (_today() - datetime.timedelta(days=days)).isoformat()
    conn.execute(
        "UPDATE wrong_items SET ts = ?, last_review = ? WHERE id = ?",
        (stamp + " 09:00:00", last_review, item_id))
    conn.commit()


class TestWrongbookStore(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_fingerprint_keeps_math_symbols(self):
        self.assertNotEqual(store.wrong_fingerprint("a+b"), store.wrong_fingerprint("a-b"))
        self.assertEqual(store.wrong_fingerprint("【第1题】/27 有多少主机？"),
                         store.wrong_fingerprint("/27 有多少主机"))

    def test_add_dedupes_by_source_id(self):
        first, created = store.add_wrong_item(
            self.conn, question="什么是子网掩码", answer="分网络位和主机位",
            source="quiz", source_id="quiz:1:abc")
        second, again = store.add_wrong_item(
            self.conn, question="什么是子网掩码", answer="重复", source="quiz",
            source_id="quiz:1:abc")
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(first, second)
        self.assertEqual(len(store.wrong_items(self.conn)), 1)

    def test_manual_without_source_id_allows_many(self):
        store.add_wrong_item(self.conn, question="题一")
        store.add_wrong_item(self.conn, question="题二")
        self.assertEqual(len(store.wrong_items(self.conn)), 2)

    def test_toggle_ask_roundtrip(self):
        ask_id = store.add_ask(self.conn, "什么是头插法", "先接后断", 10, "m")
        self.assertTrue(store.toggle_star(self.conn, ask_id))
        self.assertEqual(len(store.wrong_items(self.conn, source="ask")), 1)
        self.assertFalse(store.toggle_star(self.conn, ask_id))
        self.assertEqual(store.wrong_items(self.conn), [])
        self.assertFalse(store.toggle_star(self.conn, 999), "不存在的 id 别崩")

    def test_fsrs_review_intervals_grow(self):
        item_id, _ = store.add_wrong_item(self.conn, question="CIDR 速算")
        _shift(self.conn, item_id, 1)
        due = store.wrong_due_items(self.conn)
        self.assertEqual([item["id"] for item in due], [item_id])

        item = store.review_wrong_item(self.conn, item_id, "remember")
        self.assertEqual(item["review_reps"], 1)
        self.assertFalse(item["mastered"])
        self.assertEqual(item["scheduled_days"], 3, "新卡「记得」= 3 天")
        self.assertEqual(store.wrong_due_items(self.conn), [])

        # 把到期日拨回今天，模拟 3 天后再复习
        self.conn.execute(
            "UPDATE review_state SET due = ? WHERE item_type = 'wrong' AND item_id = ?",
            (_today().isoformat(), item_id))
        self.conn.commit()
        self.assertEqual(len(store.wrong_due_items(self.conn)), 1)
        item = store.review_wrong_item(self.conn, item_id, "remember")
        self.assertEqual(item["review_reps"], 2)
        self.assertGreater(item["scheduled_days"], 3, "间隔随历史变长")
        self.assertFalse(item["mastered"], "FSRS 不自动判定掌握")

    def test_forgot_resets_to_tomorrow(self):
        item_id, _ = store.add_wrong_item(self.conn, question="路由汇总")
        _shift(self.conn, item_id, 1)
        store.review_wrong_item(self.conn, item_id, "remember")
        item = store.review_wrong_item(self.conn, item_id, "forgot")
        self.assertEqual(item["review_lapses"], 1)
        self.assertEqual(item["scheduled_days"], 1)
        self.assertFalse(item["mastered"])
        expected = (_today() + datetime.timedelta(days=1)).isoformat()
        self.assertEqual(item["next_review"], expected)

    def test_material_id_and_facets(self):
        material_id, _ = store.add_material(
            self.conn, title="子网课件", kind="pdf", source="upload", body="正文")
        item_id, _ = store.add_wrong_item(
            self.conn, question="/27 可用主机", source="quiz",
            source_id="quiz:1:x", material_id=material_id)
        item = store.get_wrong_item(self.conn, item_id)
        self.assertEqual(item["material_id"], material_id)
        self.assertEqual(item["material_title"], "子网课件")
        self.assertEqual(store.wrong_material_facets(self.conn),
                         [{"material_id": material_id, "title": "子网课件", "count": 1}])
        self.assertEqual(len(store.wrong_items(self.conn, material_id=material_id)), 1)
        self.assertEqual(len(store.wrong_items(self.conn, material_id=999)), 0)

    def test_old_wrong_table_gets_material_column(self):
        old = sqlite3.connect(":memory:")
        old.execute("CREATE TABLE asks (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, "
                    "question TEXT, answer TEXT, ms INTEGER, backend TEXT)")
        old.execute("CREATE TABLE wrong_items (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "ts TEXT, question TEXT, answer TEXT)")
        old.commit()
        core_db._migrate_columns(old)
        cols = {row[1] for row in old.execute(
            "PRAGMA table_info(wrong_items)").fetchall()}
        self.assertIn("material_id", cols)
        old.close()

    def test_master_and_delete(self):
        item_id, _ = store.add_wrong_item(self.conn, question="VLAN")
        self.assertTrue(store.set_wrong_mastered(self.conn, item_id, True))
        self.assertTrue(store.get_wrong_item(self.conn, item_id)["mastered"])
        self.assertEqual(len(store.wrong_items(self.conn, status="mastered")), 1)
        self.assertTrue(store.set_wrong_mastered(self.conn, item_id, False))
        item = store.get_wrong_item(self.conn, item_id)
        self.assertFalse(item["mastered"])
        self.assertEqual(item["review_stage"], 0, "取消掌握后从明天重新复习")
        self.assertTrue(store.delete_wrong_item(self.conn, item_id))
        self.assertIsNone(store.get_wrong_item(self.conn, item_id))
        self.assertFalse(store.delete_wrong_item(self.conn, item_id))


class TestLegacyStarredMigration(unittest.TestCase):
    def test_migrates_once_and_does_not_revive_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "learning.db"
            conn = store.connect(path)
            conn.execute(
                "INSERT INTO asks (ts, question, answer, starred) VALUES (?, ?, ?, 1)",
                ("2026-10-01 09:00:00", "旧收藏题", "旧答案"))
            conn.execute("DELETE FROM meta WHERE key = 'wrongbook_imported_at'")
            conn.commit()
            conn.close()

            conn = store.connect(path)
            items = store.wrong_items(conn)
            self.assertEqual(len(items), 1, "旧 starred 问答要迁进错题本")
            self.assertEqual(items[0]["source"], "ask")
            self.assertEqual(items[0]["question"], "旧收藏题")
            store.delete_wrong_item(conn, items[0]["id"])
            conn.close()

            conn = store.connect(path)       # 再开一次：meta 已记，不该复活
            self.assertEqual(store.wrong_items(conn), [])
            conn.close()


class TestWrongbookCsv(unittest.TestCase):
    def test_csv_has_bom_headers_and_content(self):
        items = [{
            "question": "什么是 /27 的可用主机数", "answer": "30 个",
            "my_answer": "32 个", "note": "去掉网络地址和广播地址",
            "source": "quiz", "tags": "子网", "ts": "2026-10-20 10:00:00",
            "material_title": "子网课件.pdf",
        }]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "错题本.csv"
            count = study.export_wrongbook_csv(items, path)
            raw = path.read_bytes()
        self.assertEqual(count, 1)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "utf-8-sig 才能让 Excel 不乱码")
        text = raw.decode("utf-8-sig")
        self.assertIn("正面（问题）", text)
        self.assertIn("30 个", text)
        self.assertIn("去掉网络地址和广播地址", text)
        self.assertIn("测验错题", text)
        self.assertIn("子网课件.pdf", text)


class WrongbookApiTest(unittest.TestCase):
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

    def test_manual_add_dedupes_and_lists(self):
        body = {"source": "manual", "question": "OSPF 有几类 LSA？", "answer": "常见 1-5 类"}
        first = self.client.post("/api/wrongbook", json=body, headers=AUTH).json()
        second = self.client.post("/api/wrongbook", json=body, headers=AUTH).json()
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        data = self.client.get("/api/wrongbook?status=all", headers=AUTH).json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["counts"]["all"], 1)

    def test_quiz_add_review_master_delete(self):
        body = {"source": "quiz", "conversation_id": 12,
                "question": "【第1题】/28 有多少可用主机？", "answer": "14 个",
                "my_answer": "16 个", "tags": "子网"}
        added = self.client.post("/api/wrongbook", json=body, headers=AUTH).json()
        item_id = added["id"]
        again = self.client.post("/api/wrongbook", json=body, headers=AUTH).json()
        self.assertEqual(again["id"], item_id, "同一题不能重复收")
        self.assertEqual(again["item"]["source"], "quiz")

        reviewed = self.client.post(
            f"/api/wrongbook/{item_id}/review", json={"result": "forgot"},
            headers=AUTH).json()["item"]
        self.assertEqual(reviewed["review_stage"], 0)
        self.assertTrue(reviewed["next_review"])

        mastered = self.client.post(
            f"/api/wrongbook/{item_id}/master", json={"mastered": True},
            headers=AUTH).json()["item"]
        self.assertTrue(mastered["mastered"])
        data = self.client.get("/api/wrongbook?status=mastered", headers=AUTH).json()
        self.assertEqual(len(data["items"]), 1)

        deleted = self.client.delete(f"/api/wrongbook/{item_id}", headers=AUTH)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/wrongbook", headers=AUTH)
                         .json()["items"], [])

    def test_material_filter_and_facets(self):
        conn = self._conn()
        try:
            material_id, _ = store.add_material(
                conn, title="资料出题验收.md", kind="md", source="upload", body="正文")
        finally:
            conn.close()
        added = self.client.post("/api/wrongbook", headers=AUTH, json={
            "source": "quiz", "conversation_id": 3, "question": "/27 掩码是多少",
            "answer": "224", "material_id": material_id,
        }).json()
        self.assertEqual(added["item"]["material_id"], material_id)
        self.assertEqual(added["item"]["material_title"], "资料出题验收.md")

        filtered = self.client.get(
            f"/api/wrongbook?status=all&material_id={material_id}", headers=AUTH).json()
        self.assertEqual(len(filtered["items"]), 1)
        self.assertEqual(filtered["materials"][0]["title"], "资料出题验收.md")
        self.assertEqual(filtered["materials"][0]["count"], 1)

    def test_toggle_ask_adds_to_wrongbook(self):
        conn = self._conn()
        try:
            ask_id = store.add_ask(conn, "什么是子网掩码", "分网络位和主机位", 10, "m")
        finally:
            conn.close()
        result = self.client.post(f"/api/wrongbook/{ask_id}/toggle", headers=AUTH).json()
        self.assertTrue(result["starred"])
        items = self.client.get("/api/wrongbook", headers=AUTH).json()["items"]
        self.assertEqual(items[0]["source"], "ask")

    def test_today_due_reviews(self):
        conn = self._conn()
        try:
            item_id, _ = store.add_wrong_item(conn, question="今天到期的题")
            _shift(conn, item_id, 1)
        finally:
            conn.close()
        today = self.client.get("/api/today", headers=AUTH).json()
        self.assertEqual(today["due_reviews"], 1)

    def test_export_returns_csv(self):
        body = {"source": "manual", "question": "导出这道题", "answer": "导出答案"}
        self.client.post("/api/wrongbook", json=body, headers=AUTH)
        response = self.client.get("/api/wrongbook/export", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn("导出这道题", response.content.decode("utf-8-sig"))

    def test_xp_only_for_explicit_entries(self):
        def xp():
            return self.client.get("/api/overview", headers=AUTH).json()["today"]["xp"]

        baseline = xp()
        self.client.post("/api/wrongbook", json={
            "source": "manual", "question": "手动收的题", "answer": "答案"}, headers=AUTH)
        self.assertEqual(xp(), baseline + 3, "手动收题 +3")

        conn = self._conn()
        try:
            store.add_wrong_item(conn, question="测验自动收的题", source="quiz",
                                 source_id="quiz:99:auto", auto=True)
        finally:
            conn.close()
        self.assertEqual(xp(), baseline + 3, "自动收错题不该奖励答错")

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/wrongbook").status_code, 403)
        self.assertEqual(self.client.post("/api/wrongbook", json={"question": "x"}).status_code, 403)
        self.assertEqual(self.client.get("/api/wrongbook/export").status_code, 403)


class TestWrongbookTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        conn.close()

    def test_schema_only_in_quiz_mode(self):
        quiz = [tool["name"] for tool in tools.schemas_for("quiz")]
        explain = [tool["name"] for tool in tools.schemas_for("explain")]
        self.assertIn("save_wrongbook", quiz)
        self.assertNotIn("save_wrongbook", explain)
        self.assertIsNone(tools.schemas_for("quiz", use_tools=False))

    def test_save_and_dedupe(self):
        ctx = tools.ToolContext(
            data_root=pathlib.Path(self.tmp.name), db_path=self.db_path,
            mode="quiz", conversation_id=7, material_id=42)
        text = tools.save_wrongbook(
            "【第1题】/27 有多少可用主机？", "32", "30", "子网", ctx=ctx)
        self.assertIn("已收进错题本", text)
        again = tools.save_wrongbook(
            "【第1题】/27 有多少可用主机？", "32", "30", "子网", ctx=ctx)
        self.assertIn("已经收过", again)
        conn = store.connect(self.db_path)
        try:
            items = store.wrong_items(conn)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["material_id"], 42, "测验错题要带资料 id")
        finally:
            conn.close()

    def test_other_mode_refuses(self):
        ctx = tools.ToolContext(data_root=pathlib.Path(self.tmp.name),
                                db_path=self.db_path, mode="explain")
        text = tools.save_wrongbook("题", "答", "对", "", ctx=ctx)
        self.assertIn("只有测验模式", text)

    def test_execute_preview(self):
        ctx = tools.ToolContext(
            data_root=pathlib.Path(self.tmp.name), db_path=self.db_path,
            mode="quiz", conversation_id=8)
        content, preview, ok = tools.execute("save_wrongbook", {
            "question": "第 2 题", "my_answer": "错", "correct_answer": "对",
        }, ctx)
        self.assertTrue(ok)
        self.assertIn("已收进错题本", content)
        self.assertEqual(preview, "已收进错题本")

    def test_quiz_prompt_mentions_tool(self):
        prompt = study.build_quiz_question([], [], "")
        self.assertIn("save_wrongbook", prompt)
        self.assertIn("一次只出一题", prompt)


class TestWrongbookPlugin(unittest.TestCase):
    def test_plugin_ready(self):
        modules = load_registry()["modules"]
        module = next(item for item in modules if item["id"] == "wrongbook")
        self.assertEqual(module["status"], "ready")
        self.assertTrue(module["home"])
        self.assertTrue(module.get("script"))
        root = pathlib.Path(__file__).resolve().parents[1]
        self.assertTrue((root / "web" / module["entry"]).is_file())
        self.assertTrue((root / "web" / module["script"]).is_file())

    def test_sw_precaches_wrongbook(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        text = (root / "web" / "sw.js").read_text(encoding="utf-8")
        self.assertIn("/web/pages/wrongbook.html", text)
        self.assertIn("/web/js/pages/wrongbook.js", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
