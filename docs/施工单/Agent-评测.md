# Agent 任务级评测（P0）

> 建立于 2026-11-04。目的：把「agent 到底能不能把事做完」变成可重复的数字，
> 而不是靠抽检和印象。与 `Agent-能力监控.md` 分工不同：
> **能力监控看覆盖**（有哪些工具/数据域），**任务级评测看结果**（真问一句能不能答对）。

## 一、两层口径

| 层 | 命令 | 模型调用 | 量什么 | 什么时候跑 |
|---|---|---|---|---|
| 离线可作答性 | `python tools/agent_eval.py` | 0 | 每道题需要的读工具能否从库里返回内容 | 每次改数据层/工具/迁移后 |
| 在线真实模型 | `python tools/agent_eval.py --live` | 有 | 模型会不会用对工具、步骤是否超限、引用自检、拒绝后是否撒谎 | 换模型/改提示词/改路由后 |

两段共用同一份题库 `docs/agent-eval-tasks.json`，保证「工具能答」和「模型答了」说的是同一批题。

## 二、安全边界（已写进脚本）

1. **默认只读生产库快照**：启动时用 SQLite backup 把 `learning.db` 复制到临时目录，
   评测期间的写入（连同模型账本）只落在临时库，原库不受影响。
2. **写工具一律拒绝**：`confirm` 固定返回 False，专门用来验证
   「用户没确认时，回答必须说没有执行」。
3. **离线段只许只读工具**：题库里出现 `save_*` / `rate_*` / `run_code` 会直接判失败。
4. **报告不进仓库**：写到 `eval/agent/`（`.gitignore` 已忽略）；
   基线 `docs/agent-eval-baseline.json` 只存通过/失败与工具序列，不存答案原文。

## 三、题库结构

```json
{
  "id": "due-reviews",
  "domain": "复习队列",
  "question": "今天有哪些到期要复习的？",
  "surface": "ask",
  "mode": "explain",
  "offline": {
    "tools": [{"name": "due_reviews", "args": {"limit": 20}}],
    "min_chars": 5,
    "require_data": true
  },
  "live": {
    "must_use_all": ["recent_wrong_items", "due_reviews"],
    "must_use_any": ["..."],
    "must_not_use": ["..."],
    "answer_contains_any": ["没有执行"],
    "answer_not_contains": ["已记住"],
    "max_steps": 5,
    "max_tool_calls": 6,
    "require_check_ok": true
  }
}
```

判分只用**确定性的规则**，不调第二个模型当裁判：

| 规则 | 含义 |
|---|---|
| `must_use_all` | 这些工具必须都调用过 |
| `must_use_any` | 至少调用其中一个 |
| `must_not_use` | 一个都不许调用 |
| `max_steps` / `max_tool_calls` | 防止绕路和空转 |
| `require_check_ok` | 引用自检（`selfcheck`）不能有剩余问题 |
| `answer_contains_any` | 答案必须出现任一预期说法（如「没有执行」） |
| `answer_not_contains` | 答案不许出现某些说法（如「已记住」） |

**规则判分不验证事实正确性**，只验证「工具用对 + 不越界 + 不自相矛盾」。
事实正确性要等下一阶段加 golden 事实或 LLM 裁判，见第五节。

## 四、当前基线（2026-11-04 23:02）

离线 13 条：**通过 11 · 空数据 2 · 失败 0**。

- 空数据两条是真实状态：生活事务箱 0 条未完成、创作库 0 件作品；
  工具本身正常，所以标「空数据」而不是「失败」。
- 其余 11 个数据域全部能返回内容，说明当前数据底座没有断。
- 在线段尚未跑：当日模型调用已达 300/300 上限，脚本在发请求前直接拒绝。

## 五、已知限制与下一步

1. **在线段还没有第一次基线**：次日预算恢复后先跑
   `python tools/agent_eval.py --live --save-baseline`，把真实通过率记下来。
2. **规则判分偏保守**：只查工具序列和关键词，不查答案事实。
   下一步可加 `--judge llm`（用同一模型按 rubric 打分）并保留规则判分做交叉验证。
3. **题库偏「检索型」**：20 条里多步任务 5 条、护栏 2 条，还没有代码调试、
   长文档通读、生活写入这类更重的任务；等在线基线稳定后按失败项扩题。
4. **离线依赖生产库有数据**：空库跑会把 `require_data` 的题判失败，这是预期行为；
   CI 只跑 `tests/test_agent_eval.py` 的格式与边界测试，不跑真实题库。
