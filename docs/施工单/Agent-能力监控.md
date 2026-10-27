# Agent 能力监控 · 五个断面

> 2026-10-26 建立。目的：防止「每加一个功能，agent 工具面就落后一期」重演。
> 只读脚本：`tools/agent_capability_report.py`；基线：`docs/agent-capability-baseline.json`。

## 1. 怎么用

```bash
python tools/agent_capability_report.py          # 人看
python tools/agent_capability_report.py --json   # 机器比对
python tools/agent_capability_report.py --save   # 更新基线（只在确认有实质进展时）
```

节奏：

- **每次改 agent（工具 / 提示词 / 记忆 / 路由 / 账本）前后各跑一次**，把差异写进当次验收；
- 每个大阶段（P2x / R x）结束跑一次，未变化就不算推进；
- `--save` 只在「指标变好或口径变了」时执行，避免把临时波动写死成基线。

## 2. 指标与口径

| 断面 | 指标 | 当前基线（2026-10-27） | 目标 |
|---|---|---|---|
| 感知面 | 视觉模型 | 已启用 `deepseek-flash` | 填入视觉 key 后 `vision_ready=true` |
| 感知面 | 联网工具 | 2（`fetch_url` / `web_search`） | `fetch_url`（白名单）或 MCP 客户端 |
| 感知面 | 资料 / 录像 | 5 份 / 3 段 | 至少真实导入 5 份资料 |
| 工具面 | 工具总数（工作台 / 快捷栏 / 六级 / 速答） | 29 / 18 / 19 / 2 | 快捷栏继续瘦身；速答保持 2 |
| 工具面 | 学习数据域覆盖 | 7 / 7 | 新增数据域时同步加工具，保持 7/7 |
| 工具面 | MCP 工具 | 5 个（4 只读 + 1 写翻译缓存） | P2 评估写入工具（带确认） |
| 记忆面 | 长期记忆 | 2 条启用 / 5 条总计 | 自动抽取 + 去重后 ≥ 8 条有效 |
| 记忆面 | 会话摘要 | 0 / 28 | 新会话生成本地摘要，旧会话可回填 |
| 记忆面 | 历史窗口 | 4 轮 | 有摘要后放宽到 8 轮或按 token 预算 |
| 可靠性 | 用工具的运行占比 | 6 / 60 | 真实学习任务里 ≥ 30% 调用工具 |
| 可靠性 | 缓存命中 | 86% | ≥ 80%（下降说明上下文膨胀） |
| 可靠性 | 强模型调用 | 0（shadow） | 开 `on` 后复杂问题有可解释的升级率 |
| 可靠性 | 旁路调用入账 | deep 0 / vision 0 | 启用后来源里能看到 `deep` / `vision` |
| 主动性 | 写工具 | 12 个（全部确认） | 增到 10–12 个，覆盖生词/复习/训练 |
| 主动性 | 深度分析 | 已启用（`deepseek-v4-pro`，API 复用主模型 key） | 启用后每周至少 1 次、成本可见 |

## 3. 2026-10-26 P0 已完成（随 2.33.0 部署）

- [x] `agent/usage.py` 成为模型账本唯一写入口；主循环、看图、深度分析都走它。
- [x] 深度分析启用前先过每日预算（`budget.check`），且审计不再依赖 `store.connect()` 默认路径。
- [x] 四个只读工具上线：`due_reviews` / `get_mastery` / `get_train_summary` / `list_recordings`。
- [x] 工具按入口裁剪：速答 2 个、快捷栏 15 个、六级 16 个、工作台 23 个；
      系统工具（打开文件/启动程序/跑代码）只留在工作台问答页。
- [x] 体检脚本与基线：五个断面可一键复现。

**未完成（需要负责人）**：视觉 key 未填，`vision_ready` 仍为 false——填 `设置.json` 的
`vision.base_url / model / api_key`（模板已有智谱 / 硅基流动 / 通义）后重跑体检确认。
（2026-10-27 已由 2.33.1 的「视觉 key 留空复用主模型」解决，`vision_ready=true`。）

## 3.1 2026-10-27 P25.2 已完成（2.35.0）

- [x] 写工具 8 → 12：`add_vocab` / `delete_vocab` / `rate_review` / `save_training_error`，
      全部进 `WRITE_TOOLS` + `CONFIRM_TOOLS`，覆盖生词 / 复习 / 训练三块。
- [x] 入口裁剪：快捷栏只加 `add_vocab`（18）；六级加 3 个（19）；录像只加 `add_vocab`（17）；
      工作台问答 29；速答仍 2。
- [x] 资料库 0 → 5 份（2024-06 写作解析 3 份 + 2024-12 写作解析 2 份），
      检索、挂资料、从资料出题均已实测。
- [x] MCP 写工具评估结论：继续只读，原因与「提议箱」方案写进 `docs/MCP接入.md`。

## 3.2 2026-10-27 P25.3 已完成（2.36.0）

- [x] 深度分析 API 模式支持**复用主模型**的 base/key，`model` 留空用 `strong_model`；
      密钥仍只有一份，不复制进深度分析配置。
- [x] 生产启用：`agent.deep.enabled=true`、`model=deepseek-v4-pro`，其余留空。
- [x] 真机一次 21.7 秒、中文回答正确；`agent_runs` 有 `mode=deep`，
      `model_usage` 有 `source=deep`（118 prompt + 1034 completion，0.02898 CNY）。
- [x] `test_deep_analysis.py` 隔离真实 `设置.json`，不再因本机启用而红。

## 4. 判定规则

- 工具面：**只要新增了数据域（新表 / 新接口），当次必须同时有对应读工具**，否则体检的
  「数据域覆盖」会掉；掉一次就在施工单记一次债。
- 记忆面：摘要与自动抽取上线后，用「回忆 10-23 文件系统对话」这类固定问题做回归。
- 可靠性：`prompt_tokens` 单次 explain 超过 6k 视为回退（当前约 4.9k）。
- 主动性：写工具增加必须同时进 `CONFIRM_TOOLS`，确认框文案要能看出改什么。
