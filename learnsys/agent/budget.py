"""每日成本 / 调用上限：唯一的检查点。

`agent.run()` 在准备阶段调用一次 `check()`；达到上限就整轮拒绝，
不再发起任何模型请求。账本只有一份（`model_usage`），这里只读不写。

口径：
- `daily_cost_limit` 需要设置了单价才有意义；没配单价时成本恒为 0。
- 上限按「今天已完成的调用」算；当前这一轮最多超出一条的用量。
- 0 = 不限。
"""
from __future__ import annotations

import contextlib

from learnsys import config, diagnostics, store


def limits(cfg) -> tuple[float, int]:
    return (float(getattr(cfg, "daily_cost_limit", 0) or 0),
            int(getattr(cfg, "daily_call_limit", 0) or 0))


def totals(cfg) -> dict:
    """今天已用多少；读不到库时按 0 算（不能让账本问题挡住所有问答）。"""
    path = config.db_path_in(getattr(cfg, "data_root", config.DATA_ROOT))
    try:
        with contextlib.closing(store.connect(path)) as conn:
            return store.day_totals(conn)
    except Exception as exc:  # noqa: BLE001 —— 账本坏了也不能让对话整体不可用
        diagnostics.log_swallow("读取每日用量", exc, data_root=cfg.data_root)
        return {"day": "", "calls": 0, "cost": 0.0, "tokens": 0, "currency": ""}


def check(cfg) -> str | None:
    """超限返回中文原因；没超返回 None。"""
    cost_limit, call_limit = limits(cfg)
    if not (cost_limit or call_limit):
        return None
    used = totals(cfg)
    if call_limit and used["calls"] >= call_limit:
        return (f"今天的模型调用已达上限（{used['calls']} / {call_limit} 次）。\n"
                "要临时放开：打开「设置 → 成本估算」，把「每日调用上限」调高或设为 0。")
    if cost_limit and used["cost"] >= cost_limit:
        currency = used.get("currency") or ""
        return (f"今天的模型花费已达上限（{used['cost']:.4f} / {cost_limit:.4f} {currency}）。\n"
                "要临时放开：打开「设置 → 成本估算」，把「每日成本上限」调高或设为 0。")
    return None
