"""模型调用账本的唯一写入口。

所有真正花钱的模型调用（主对话、自检重写、深度分析、看图）都必须走这里，
否则「运行记录 / 每日上限」就只统计了一半。

约定：
- 只记成功调用的 usage；失败或没有 usage 的调用不记（避免把失败重试算成花费）。
- 记账失败只写诊断日志，不让主流程失败。
- 成本按调用时的配置单价估算；未配置单价时成本为 0（与设置页口径一致）。
"""
from __future__ import annotations

import contextlib
import pathlib

from learnsys import config, diagnostics, store
from learnsys.agent import cost as agent_cost


def record(data_root, *, source: str, model: str, usage: dict,
           cfg=None) -> tuple[float, str]:
    """写一条 `model_usage`；返回 (金额, 币种)。

    `cfg` 用来取单价与币种；传当前运行配置，避免重新加载后与用户刚改的设置打架。
    不传时按默认配置估价。
    """
    if not isinstance(usage, dict) or not usage:
        return 0.0, ""
    if cfg is None:
        from learnsys.llm.config import load_config
        cfg = load_config()
    model = str(model or "")
    amount, currency, _ = agent_cost.estimate(usage, cfg, model)
    try:
        path = config.db_path_in(
            pathlib.Path(data_root or getattr(cfg, "data_root", config.DATA_ROOT)))
        with contextlib.closing(store.connect(path)) as conn:
            store.add_model_usage(
                conn, source=str(source or ""), model=model,
                counts=agent_cost.normalize_usage(usage),
                cost=amount, currency=currency)
    except Exception as exc:  # noqa: BLE001 —— 记账失败不能挡住主流程
        diagnostics.log_swallow("记录模型用量", exc, data_root=data_root)
    return amount, currency
