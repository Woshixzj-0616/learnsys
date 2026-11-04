"""六级写作 / 翻译训练的**业务服务**层。

与顶层 `learnsys/train/`（纯逻辑：内容、档位、提示词、输出校验）区分：
- 这里管任务队列、提交生命周期、缓存与统计，依赖 store / agent / llm
- `plan`    今日训练计划（到期错误卡 → 未练科目 → 下一题）
- `review`  批改任务：3 次取中位、单句同步审核、`service_results` 缓存
- `sentences` 一句一译题库与尝试落库
- `stats`  档位趋势 / 错误画像 / 训练量（只读）
- `submissions` 草稿、自动保存、提交、轮询落库、二稿

注意：`train.review` 是写作/翻译批改，不是通用复习（通用复习在 `services/review.py`）。
"""
from __future__ import annotations

# 显式导入子模块：供 PyInstaller 静态收集（与 services/life、services/web 同惯例）。
from . import plan, review, sentences, stats, submissions

__all__ = ["plan", "review", "sentences", "stats", "submissions"]
