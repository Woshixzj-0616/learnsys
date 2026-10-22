"""数据路由共享：连接工厂与行转换。

测试要换临时库时 patch `routes_data.common._conn`（包级同名符号只做转发）。
"""
from __future__ import annotations

from learnsys import store


def _conn():
    """测试里可以 monkeypatch 这个函数，换成临时库。"""
    return store.connect()


def _ask_dict(row) -> dict:
    return {
        "ts": row[0], "question": row[1], "answer": row[2],
        "kind": row[3] or "text", "image_path": row[4] or "", "id": row[5],
        "conversation_id": row[6] if len(row) > 6 else None,
    }
