# -*- coding: utf-8 -*-
"""把智能旅行的架构资料导入学习工作台（默认只预演，--apply 才写库）。

三份来源（只读，不修改智能旅行仓库）：
    docs/architecture/症状与排查.md
    docs/architecture/行为开关总表.md
    docs/architecture/架构.md

导入后课程名统一是「智能旅行后端」，和已有的 5 份学习包放在一起；
同名 / 同内容都跳过，只增不删。写库前备份 learning.db。

用法：
    python -X utf8 tools/import_travel_architecture.py --dry-run
    python -X utf8 tools/import_travel_architecture.py --apply
    python -X utf8 tools/import_travel_architecture.py --base http://127.0.0.1:8766 --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
TRAVEL_DOCS = pathlib.Path(r"D:\Desktop\智能旅行\docs\architecture")
COURSE = "智能旅行后端"
TAGS = "agent,架构,排错"

SOURCES = [
    ("智能旅行后端 · 症状与排查", "症状与排查.md"),
    ("智能旅行后端 · 行为开关总表", "行为开关总表.md"),
    ("智能旅行后端 · 架构总览", "架构.md"),
]


def _request(base: str, path: str, token: str = "", method: str = "GET",
             payload: dict | None = None):
    url = base.rstrip("/") + path
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["x-learnsys-token"] = token
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError("HTTP %s：%s" % (exc.code, body)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("连不上学习工作台：%s" % exc) from exc


def _backup(db_path: str) -> str:
    source = pathlib.Path(db_path)
    if not source.exists():
        return "（没找到库文件，跳过备份）"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = source.with_name(f"{source.name}.bak-{stamp}-智能旅行架构资料")
    shutil.copy2(source, dest)
    return str(dest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    apply = args.apply and not args.dry_run

    missing = [name for _, name in SOURCES if not (TRAVEL_DOCS / name).exists()]
    if missing:
        print("找不到这些文档：" + "、".join(missing))
        print(f"请确认智能旅行仓库在：{TRAVEL_DOCS}")
        return 1

    try:
        health = _request(args.base, "/api/health")
    except RuntimeError as exc:
        print(str(exc))
        print("\n先把学习工作台后台拉起来（默认 127.0.0.1:8765），再跑这条命令。")
        return 1
    token = str(health.get("token") or "")
    print("学习工作台：v%s · 端口 %s · 库 %s" % (
        health.get("version"), health.get("port"), health.get("db")))

    existing = _request(
        args.base, "/api/materials?course=%s&limit=200"
        % urllib.parse.quote(COURSE), token)
    titles = {str(item.get("title") or "") for item in existing.get("items") or []}

    notes = []
    for title, name in SOURCES:
        body = (TRAVEL_DOCS / name).read_text(encoding="utf-8")
        notes.append({
            "title": title,
            "body": body,
            "chars": len(body),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "exists": title in titles,
        })

    for note in notes:
        mark = "已存在，跳过" if note["exists"] else "待导入"
        print("[%s] %s · %d 字 · sha256 %s…" % (
            "预演" if not apply else "执行", note["title"], note["chars"],
            note["sha256"][:12]))
        print("       " + mark)
    if not apply:
        print("\n预演结束；确认无误后加 --apply 写入。")
        return 0

    backup = _backup(str(health.get("db") or ""))
    print("\n已备份：" + backup)

    for note in notes:
        if note["exists"]:
            continue
        data = _request(args.base, "/api/materials/note", token, "POST", {
            "title": note["title"],
            "body": note["body"],
            "course": COURSE,
            "tags": TAGS,
            "sha256": note["sha256"],
        })
        item = data.get("item") or {}
        state = "已建" if data.get("created") else "内容已存在"
        print("%s：%s → id=%s" % (state, note["title"], item.get("id")))
    print("\n完成。打开工作台 → 资料 → 课程「%s」查看。" % COURSE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
