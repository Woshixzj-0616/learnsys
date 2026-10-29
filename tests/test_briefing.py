"""每日简报：store / RSS / 筛选 / 摘要 / 生成 / API / 调度。"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.modules import load_registry, web_dir
from learnsys.server import app as server_app
from learnsys.services.briefing import feed, pick, runner, summarize
from learnsys.services.briefing.sources import RawItem

TOKEN = "briefing-test-token"


def _raw(title: str, url: str, *, source="s1", weight=1.0, hint="ai",
         summary="", published="2026-10-28 10:00") -> RawItem:
    return RawItem(source, f"源-{source}", weight, hint, title, url,
                   summary, published)


class TestBriefingStore(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_create_claim_and_items(self):
        briefing_id, created = store.create_briefing_day(self.conn, "2026-10-28")
        self.assertTrue(created)
        self.assertEqual(store.create_briefing_day(self.conn, "2026-10-28")[0],
                         briefing_id)
        self.assertEqual(store.claim_briefing(self.conn, "2026-10-28"), briefing_id)
        self.assertIsNone(store.claim_briefing(self.conn, "2026-10-28"))

        items = [{"category": "ai", "title": "标题", "summary": "摘要",
                  "url": "https://example.com/1", "url_key": "k1",
                  "source": "源", "published_at": "2026-10-28 10:00",
                  "meta": {"summary_source": "model"}}]
        self.assertEqual(store.save_briefing_items(self.conn, briefing_id, items), 1)
        row = store.get_briefing_day(self.conn, "2026-10-28")
        item_id = row["items"][0]["id"]
        updated = store.update_briefing_item(self.conn, item_id, read=True, starred=True)
        self.assertTrue(updated["read"])
        self.assertTrue(updated["starred"])

        store.finish_briefing(self.conn, briefing_id, status="ready",
                              title="简报", intro="导语", item_count=1)
        self.assertEqual(store.claim_briefing(self.conn, "2026-10-28", force=True),
                         briefing_id)
        store.save_briefing_items(self.conn, briefing_id, items)
        row = store.get_briefing_day(self.conn, "2026-10-28")
        self.assertTrue(row["items"][0]["read"])
        self.assertTrue(row["items"][0]["starred"])
        self.assertEqual(store.read_all_briefing(self.conn, "2026-10-28"), 0)

    def test_recent_seen_and_recover(self):
        briefing_id, _ = store.create_briefing_day(self.conn, "2026-10-28")
        store.save_briefing_items(self.conn, briefing_id, [{
            "category": "ai", "title": "旧标题", "url": "https://e.com/x",
            "url_key": "old", "source": "源", "published_at": "2026-10-28 10:00",
        }])
        seen = store.recent_briefing_seen(self.conn, days=3)
        self.assertEqual(seen[0]["url_key"], "old")
        self.assertEqual(store.recent_briefing_seen(
            self.conn, days=3, before_day="2026-10-28"), [])
        self.conn.execute(
            "UPDATE briefings SET status='running', updated_at='2020-01-01 00:00:00' "
            "WHERE id=?", (briefing_id,))
        self.conn.commit()
        self.assertEqual(store.recover_stale_briefings(self.conn, minutes=10), 1)
        self.assertEqual(store.get_briefing_day(self.conn, "2026-10-28")["status"],
                         "failed")


class TestBriefingFeed(unittest.TestCase):
    def test_rss_and_atom(self):
        rss = b"""<?xml version="1.0" encoding="utf-8"?>
        <rss><channel><title>T</title>
          <item><title>Hello &amp; World</title>
            <link>https://example.com/a?utm_source=x</link>
            <description><![CDATA[<p>Body <b>text</b></p>]]></description>
            <pubDate>Wed, 28 Oct 2026 10:00:00 +0800</pubDate></item>
          <item><title>No link</title></item>
        </channel></rss>"""
        items = feed.parse_feed(rss, mock.Mock(url="https://example.com/rss"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Hello & World")
        self.assertIn("Body text", items[0].summary)
        self.assertEqual(items[0].published_at, "2026-10-28 10:00")

        atom = """<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>Atom 标题</title>
            <link rel="alternate" href="https://example.com/b"/>
            <summary>Atom 摘要</summary>
            <published>2026-10-28T02:00:00Z</published></entry>
        </feed>""".encode()
        items = feed.parse_feed(atom, mock.Mock(url="https://example.com/feed"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://example.com/b")
        self.assertTrue(items[0].published_at)

    def test_gbk_and_entity_rejected(self):
        gbk = ('<?xml version="1.0" encoding="gb2312"?><rss><channel>'
               '<item><title>中文标题</title><link>https://e.com/g</link>'
               '</item></channel></rss>').encode("gb2312")
        items = feed.parse_feed(gbk, mock.Mock(url="https://e.com/rss"))
        self.assertEqual(items[0].title, "中文标题")
        with self.assertRaises(ValueError):
            feed.parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY y "z">]><rss/>',
                            mock.Mock(url="https://e.com/rss"))


class TestBriefingPick(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 28, 12, 0)

    def test_url_and_title_dedup(self):
        first = _raw("AI 芯片发布", "https://a.com/x?utm_source=1")
        second = _raw("AI 芯片发布", "https://b.com/y")
        self.assertEqual(pick.url_key("https://a.com/x?utm_source=1"),
                         pick.url_key("https://a.com/x"))
        chosen = pick.select([first, second], now=self.now)
        self.assertEqual(len(chosen), 1)

    def test_window_and_seen(self):
        old = _raw("旧闻", "https://a.com/old", published="2026-10-26 00:00")
        new = _raw("新闻", "https://a.com/new", published="2026-10-28 10:00")
        chosen = pick.select([old, new], now=self.now)
        self.assertEqual([row["title"] for row in chosen], ["新闻"])
        chosen = pick.select([new], now=self.now,
                             seen_url_keys={pick.url_key(new.url)})
        self.assertEqual(chosen, [])

    def test_classify_and_source_cap(self):
        self.assertEqual(pick.classify(_raw("英伟达发布新 GPU", "u")), "hardware")
        self.assertEqual(pick.classify(_raw("开源软件发布", "u")), "internet")
        self.assertEqual(pick.classify(_raw("新能源电池突破", "u")), "energy")
        items = [_raw(f"AI 大模型 {index}", f"https://a.com/{index}",
                      source="same", published=f"2026-10-28 1{index}:00")
                 for index in range(4)]
        chosen = pick.select(items, now=self.now, max_per_source=2, quotas={"ai": 3})
        self.assertLessEqual(len(chosen), 2)

    def test_quotas_and_backfill(self):
        items = [_raw(f"时政新闻 {i}", f"https://a.com/p{i}", source=f"s{i}",
                      hint="politics", published="2026-10-28 10:00")
                 for i in range(3)]
        items += [_raw(f"AI 新闻 {i}", f"https://b.com/a{i}", source=f"t{i}",
                       hint="ai", published="2026-10-28 11:00")
                  for i in range(3)]
        chosen = pick.select(items, now=self.now, quotas={"politics": 1, "ai": 1},
                             min_items=2, max_items=3)
        self.assertEqual(len(chosen), 2)
        self.assertEqual({row["category"] for row in chosen}, {"politics", "ai"})


class TestBriefingSummarize(unittest.TestCase):
    def test_parse_and_fallback(self):
        data = summarize.parse_reply('```json\n{"intro":"导语","items":[{"id":1,'
                                     '"summary":"摘要"}]}\n```')
        self.assertEqual(data["intro"], "导语")
        items = [{"title": "标题", "summary": "原文摘要" * 30}]
        intro, rows, fallback = summarize._rows(items, data)
        self.assertEqual(intro, "导语")
        self.assertEqual(rows[0]["summary"], "摘要")
        self.assertEqual(fallback, 0)
        _, rows, fallback = summarize._rows(items, None)
        self.assertEqual(fallback, 1)
        self.assertEqual(rows[0]["summary_source"], "feed")

    def test_model_call(self):
        cfg = mock.Mock(ready=True)
        items = [{"title": "标题", "summary": "素材", "category": "ai",
                  "source_name": "源", "published_at": "2026-10-28 10:00"}]
        payload = json.dumps({"intro": "导语",
                              "items": [{"id": 1, "title_zh": "", "summary": "摘要"}]})
        with mock.patch.object(summarize, "_call", return_value=(payload, "")):
            intro, rows, error = summarize.summarize(items, cfg=cfg)
        self.assertEqual(intro, "导语")
        self.assertEqual(rows[0]["summary"], "摘要")
        self.assertEqual(error, "")

    def test_not_ready(self):
        cfg = mock.Mock(ready=False)
        intro, rows, error = summarize.summarize(
            [{"title": "标题", "summary": "原文"}], cfg=cfg)
        self.assertEqual(intro, "")
        self.assertEqual(rows[0]["summary_source"], "feed")
        self.assertIn("没配置", error)


class TestBriefingRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        self.orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect", side_effect=lambda path=None: self.orig(path or self.db))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.cfg = mock.Mock(model="deepseek-flash", fast_model="deepseek-flash")
        self.cfg.model_for.return_value = ""
        runner._PENDING.clear()

    def _item(self):
        stamp = (dt.datetime.now() - dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        return _raw("AI 大模型发布", "https://example.com/a", published=stamp)

    def test_generate_ready_and_idempotent(self):
        day = runner.day_of()
        stats = {"s1": {"name": "源", "status": "ok", "count": 1}}
        with mock.patch.object(runner.feed, "fetch_all", return_value=([self._item()], stats)) as fetch, \
                mock.patch.object(runner.feed, "fetch_bodies", return_value=0), \
                mock.patch.object(runner.summarizer, "summarize",
                                  return_value=("导语", [{"title_zh": "", "summary": "摘要",
                                                          "summary_source": "model"}], "")), \
                mock.patch.object(runner, "load_config", return_value=self.cfg):
            out = runner.generate(day)
            self.assertEqual(out["status"], "ready")
            self.assertEqual(out["item_count"], 1)
            self.assertEqual(out["items"][0]["summary"], "摘要")
            again = runner.generate(day)
            self.assertEqual(again["status"], "ready")
            self.assertEqual(fetch.call_count, 1)
            forced = runner.generate(day, force=True)
            self.assertEqual(forced["status"], "ready")
            self.assertEqual(forced["item_count"], 1)
            self.assertEqual(fetch.call_count, 2)

    def test_generate_partial_and_failed(self):
        day = runner.day_of()
        stats = {"s1": {"name": "源", "status": "error", "count": 0}}
        with mock.patch.object(runner.feed, "fetch_all", return_value=([self._item()], stats)), \
                mock.patch.object(runner.feed, "fetch_bodies", return_value=0), \
                mock.patch.object(runner.summarizer, "summarize",
                                  return_value=("", [{"title_zh": "", "summary": "原文",
                                                      "summary_source": "feed"}],
                                                "模型失败")), \
                mock.patch.object(runner, "load_config", return_value=self.cfg):
            out = runner.generate(day, force=True)
            self.assertEqual(out["status"], "partial")
        with mock.patch.object(runner.feed, "fetch_all", return_value=([], {})):
            out = runner.generate(day, force=True)
            self.assertEqual(out["status"], "failed")


class TestBriefingApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.db = root / "learning.db"
        self.settings = root / "设置.json"
        conn = store.connect(self.db)
        conn.close()
        self.orig = store.connect
        patches = [
            mock.patch.object(store, "connect",
                              side_effect=lambda path=None: self.orig(path or self.db)),
            mock.patch.object(app_config, "DATA_ROOT", root / "data"),
            mock.patch.object(app_config, "SETTINGS_FILE", self.settings),
            mock.patch.object(app_config, "USER", {}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = server_app.create_app(token=TOKEN)
        self.client = TestClient(self.app)
        self.headers = {"X-Learnsys-Token": TOKEN}
        runner._PENDING.clear()

    def test_today_days_and_settings(self):
        response = self.client.get("/api/briefing/today", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()["status"], ("missing", "scheduled"))
        self.assertEqual(self.client.get("/api/briefing/days",
                                         headers=self.headers).status_code, 200)
        settings = self.client.get("/api/settings", headers=self.headers).json()
        self.assertIn("briefing", settings)
        saved = self.client.post("/api/settings", headers=self.headers,
                                 json={"briefing": {"enabled": False,
                                                    "generate_at": "08:15"}})
        self.assertEqual(saved.status_code, 200)
        again = self.client.get("/api/settings", headers=self.headers).json()
        self.assertFalse(again["briefing"]["enabled"])
        self.assertEqual(again["briefing"]["generate_at"], "08:15")

    def test_generate_item_and_read_all(self):
        day = runner.day_of()
        conn = store.connect(self.db)
        briefing_id, _ = store.create_briefing_day(conn, day)
        store.save_briefing_items(conn, briefing_id, [{
            "category": "ai", "title": "标题", "summary": "摘要",
            "url": "https://e.com/1", "url_key": "k1", "source": "源",
            "published_at": "2026-10-28 10:00",
        }])
        store.finish_briefing(conn, briefing_id, status="ready", item_count=1)
        item_id = store.get_briefing_day(conn, day)["items"][0]["id"]
        conn.close()

        response = self.client.patch(f"/api/briefing/items/{item_id}",
                                     headers=self.headers,
                                     json={"read": True, "starred": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["item"]["starred"])
        self.assertEqual(self.client.post("/api/briefing/read-all",
                                          headers=self.headers,
                                          json={"day": day}).status_code, 200)
        generated = self.client.post("/api/briefing/generate", headers=self.headers,
                                     json={"day": day, "force": True})
        self.assertEqual(generated.status_code, 202)
        self.assertEqual(self.client.patch("/api/briefing/items/999999",
                                           headers=self.headers, json={}).status_code,
                         404)
        self.assertEqual(self.client.get("/api/briefing/today").status_code, 403)


class TestBriefingScheduler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        self.orig = store.connect
        patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self.orig(path or self.db))
        patcher.start()
        self.addCleanup(patcher.stop)
        runner._PENDING.clear()

    def test_due_and_disabled(self):
        self.assertFalse(runner._due(dt.datetime(2026, 10, 28, 7, 29), "07:30"))
        self.assertTrue(runner._due(dt.datetime(2026, 10, 28, 7, 30), "07:30"))
        with mock.patch.object(runner, "briefing_settings",
                               return_value={"enabled": False, "generate_at": "07:30"}), \
                mock.patch.object(runner, "submit") as submit:
            runner.scheduler_tick(dt.datetime(2026, 10, 28, 12, 0))
            submit.assert_not_called()

    def test_submit_when_due(self):
        with mock.patch.object(runner, "briefing_settings",
                               return_value={"enabled": True, "generate_at": "07:30"}), \
                mock.patch.object(runner, "submit") as submit:
            runner.scheduler_tick(dt.datetime(2026, 10, 28, 12, 0))
            submit.assert_called_once()
        conn = store.connect(self.db)
        # 用被模拟的那一刻取日期：`day_of()` 不传参数会拿真实今天，
        # 测试跨天后会对不上「10-28 已生成」而误报。
        day = runner.day_of(dt.datetime(2026, 10, 28, 12, 0))
        briefing_id, _ = store.create_briefing_day(conn, day)
        store.finish_briefing(conn, briefing_id, status="ready")
        conn.close()
        with mock.patch.object(runner, "briefing_settings",
                               return_value={"enabled": True, "generate_at": "07:30"}), \
                mock.patch.object(runner, "submit") as submit:
            runner.scheduler_tick(dt.datetime(2026, 10, 28, 12, 0))
            submit.assert_not_called()


class TestBriefingPlugin(unittest.TestCase):
    def test_manifest_and_assets(self):
        registry = load_registry()
        ids = {module.get("id") for module in registry.get("modules", [])}
        self.assertIn("briefing", ids)
        root = web_dir()
        for name in ("pages/briefing.html", "js/pages/briefing.js",
                     "css/briefing.css"):
            self.assertTrue((root / name).exists(), name)
        sw = (root / "sw.js").read_text(encoding="utf-8")
        self.assertIn("/web/pages/briefing.html", sw)
        self.assertIn("/web/js/pages/briefing.js", sw)


if __name__ == "__main__":
    unittest.main()
