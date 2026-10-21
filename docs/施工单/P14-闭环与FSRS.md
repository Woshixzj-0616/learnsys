# P14 · 闭环与 FSRS

> 2026-10-21。对应 `00-阶段总览.md` 的 P14：今日计划、统一复习队列、FSRS + `review_log`。
> **目标**：到期错题一屏可见；复习间隔随个人历史变化。旧的 1/3/7 固定间隔退休。

## 1. 范围

| 切片 | 内容 | 用户可见 |
|---|---|---|
| A | FSRS-5 调度器（纯函数）+ `review_state` / `review_log` 两表 | 否 |
| B | 统一复习队列 `/api/review/*`：错题 + 生词都能排队 | 是：错题本按到期顺序 |
| C | 错题本改四档反馈（忘了 / 模糊 / 记得 / 简单） | 是 |
| D | 今日页「今日计划」显示到期数与已复习数 | 是 |

**不做**：BKT 掌握度、按课程自动生成计划、跨端同步、Anki 调度导入。

## 2. 数据

```sql
CREATE TABLE IF NOT EXISTS review_state (
    item_type     TEXT NOT NULL,              -- wrong / vocab
    item_id       INTEGER NOT NULL,
    state         TEXT NOT NULL DEFAULT 'new',-- new / learning / review
    due           TEXT NOT NULL,              -- YYYY-MM-DD
    stability     REAL NOT NULL DEFAULT 0,
    difficulty    REAL NOT NULL DEFAULT 0,
    reps          INTEGER NOT NULL DEFAULT 0,
    lapses        INTEGER NOT NULL DEFAULT 0,
    last_review   TEXT NOT NULL DEFAULT '',   -- YYYY-MM-DD HH:MM:SS
    scheduled_days INTEGER NOT NULL DEFAULT 0,
    elapsed_days  INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (item_type, item_id)
);
CREATE INDEX IF NOT EXISTS idx_review_due ON review_state (due);

CREATE TABLE IF NOT EXISTS review_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    item_type      TEXT NOT NULL,
    item_id        INTEGER NOT NULL,
    rating         INTEGER NOT NULL,          -- 1 忘了 / 2 模糊 / 3 记得 / 4 简单
    state_before   TEXT NOT NULL DEFAULT '',
    due_before     TEXT NOT NULL DEFAULT '',
    due_after      TEXT NOT NULL DEFAULT '',
    stability      REAL NOT NULL DEFAULT 0,
    difficulty     REAL NOT NULL DEFAULT 0,
    elapsed_days   INTEGER NOT NULL DEFAULT 0,
    scheduled_days INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_review_log_item
ON review_log (item_type, item_id, id DESC);
```

**单一真源**：`review_state` 是唯一调度状态；`wrong_items.review_stage / last_review` 退为历史列，
不再写；`wrong_items.mastered` 仍由用户手动控制（FSRS 不自动判定「掌握」）。
`wrong_items.next_review` 改为读 `review_state.due`，没有状态时回退旧算法（迁移前数据）。

## 3. FSRS-5

实现 `learnsys/services/fsrs.py`（纯函数，不碰数据库）：

- 默认 19 个权重 `DEFAULT_W`；目标记忆率 90%。
- 记忆公式 `R(t,S) = (1 + 19/81 · t/S)^(-0.5)`。
- 初始：`S0(r)=w[r-1]`，`D0(r)=clamp(w[4]-(r-3)·w[5], 1, 10)`。
- 复习：按 `rating` 分别走「遗忘」或「回忆」公式；同日复习走短期稳定度
  `S' = S·exp(w[17]·(r-3+w[18]))`。
- 难度均值回归：`D' = w[7]·D0(4) + (1-w[7])·(D-w[6]·(r-3))`。
- 下次间隔：`I = S/19·81·(0.9^(-2)-1)`，取整并夹在 `[1, 3650]` 天；
  `rating=1` 固定明天。
- 输出：`{state, due, stability, difficulty, reps, lapses, last_review, scheduled_days, elapsed_days}`。

单元测试必须能看出「间隔随历史变化」：连续「记得」的间隔严格递增；
评「简单」的间隔大于「记得」；评「忘了」后稳定度下降、`lapses+1`。

## 4. 接口

```
GET  /api/review/queue?limit=50&item_type=      到期卡（含 new）
POST /api/review/{item_type}/{item_id}          {rating:1..4}
GET  /api/review/stats                          {due,new,total,reviewed_today,next_due}
GET  /api/review/log?limit=20                   最近复习记录
```

- `item_type` 支持 `wrong` / `vocab`；别的类型 400。
- 队列项带卡片内容：错题带 `question/answer/my_answer/tags/note`，生词带
  `word/meaning/context/paper_title`；都带 `due/state/reps/lapses/stability/difficulty`。
- 旧的 `/api/wrongbook/{id}/review {result:remember|forgot}` 保留为兼容包装：
  `remember → rating 3`、`forgot → rating 1`，内部调用同一个 FSRS 入口。

## 5. 前端

- 错题本：四档按钮；提交后显示「下次 X 天（YYYY-MM-DD）」；卡片显示「复习 N 次 · 遗忘 M 次」。
- 今日页：「待复习」卡片改为「今日计划」：到期 N 条、今日已复习 M 条、下张到期日；
  点「开始复习」跳到 `#/wrongbook`。
- 不再展示「复习过 1/2/3 轮」；旧 `review_stage` 只作迁移种子。

## 6. 迁移

`review.seed_states(conn)` 懒执行（首次访问队列/统计时）：

- 只处理未掌握、且 `review_state` 里没有记录的 `wrong_items`。
- 种子：`state = 'new'`（若旧 stage=0）否则 `'review'`；
  `stability = max(1, 旧间隔)`；`difficulty = 5`；`reps = stage`；
  `due = 旧 next_review`（空则今天）；`last_review = 旧 last_review`。
- 幂等；不删除旧列。

## 7. 测试

- `tests/test_fsrs.py`：初始四档、同日复习、连续记得递增、简单 > 记得、遗忘降稳定度、
  间隔上下限、90% 记忆率映射。
- `tests/test_review_api.py`：到期队列、四档提交写 `review_log` 与 `review_state`、
  兼容包装映射、非法类型/评分、统计、迁移种子幂等。
- 更新 `tests/test_wrongbook.py` 里依赖 1/3/7 的断言（改成 FSRS 语义）。

## 8. 验收

1. 全量后端测试通过（当前 388 + 新增）。
2. 真实库：到期错题一屏可见（`/api/review/queue` 有卡片）。
3. 同一张卡连续「记得」三次，间隔严格递增；「忘了」后回到 1 天。
4. 今日页显示今日计划数字；错题本四档按钮可用。
5. 一个 commit；不 push、不发版。
