"""六级训练域服务：试卷读取、听写、真题自评、意群、纠音、整卷审计。

纯业务层；SQL 在 `store.cet6*`，评分内容在 `learnsys.train`。
- `paper`  `data.js` / `transcript.json` 唯一读取入口
- `drill`  专项听写队列与词级差异
- `exam`   真题自评队列与分段正确率
- `chunk`  意群长句切分与回放
- `pron`   从精听笔记解析纠音点
- `sync`   整卷审计（写前比对、空快照保护、写后校验）
- `daily_accum` 每日积累：好句/翻译词轮换、纠音池、当天冻结
"""
from __future__ import annotations

# 显式导入子模块：供 PyInstaller 静态收集（与 services/life、services/web 同惯例）。
from . import chunk, daily_accum, drill, exam, paper, pron, sync

__all__ = ["chunk", "daily_accum", "drill", "exam", "paper", "pron", "sync"]
