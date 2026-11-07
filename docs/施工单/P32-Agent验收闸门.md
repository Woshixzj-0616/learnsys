# P32 · Agent 验收闸门（Warden）

> 2026-11-05 设计稿，未施工。目标版本 **2.59.0**（待定）。
> 承接 P26.1–P26.5（派活 / 审批 / 队列 / 任务链 / 归属）。
> 背景：当前 `done` 只表示「进程正常退出」，不表示「做对了」；
> 队列只剩 `has_result`，验收链路是空的。本阶段补第一层：**确定性验收**。

## 0. 一句话

任务派出去之前先记下工作区快照，跑完再比一次：**只读任务真的没写、写入没有越界、
产物文件在**——全用脚本判，不调模型，零额外模型成本。

## 1. 方案决策

| 决策 | 结论 | 理由 |
|---|---|---|
| 谁判 | **纯确定性脚本**（`warden.py`） | 第一期不引入 LLM 裁判，避免「自己验自己」 |
| 什么时候判 | `runner._run` 的 `finally` 里，进程退出之后 | 与现有落 status 同一处，不新增线程 |
| 改不改 `status` | **不改**，终态仍是 `done/failed/cancelled` | `route.py` 的完成率口径不动，避免第一期牵连路由 |
| 结果存在哪 | 新列 `verdict_state` + `verdict_json` | 列表只查短字段，详情才查全文 |
| 契约从哪来 | **默认自动生成**，用户可选覆盖 | 不填也在验；否则没人会写契约 |
| 验收自己出错 | 一律 `error`，**绝不算通过** | 「假绿比红灯更糟」 |
| 越界判定 | 前后快照差集，不在 `scope.roots` 内即失败 | 不信任 agent 自述 |
| 只读任务 | 默认要求**零改动** | 这是最值钱的一条检查，成本为零 |
| 父任务验收失败，子任务放不放行 | **第一期放行**，只标红 | `claim_next` 不动；观察后再收紧 |

### 待拍板（施工前确认）

1. **默认契约不可关闭**：即使不填，也自动挂「只读零改动 / 写入不越界」两条。
   建议采纳——否则这个功能永远没人用。
2. **`command_zero` 默认关闭**：允许跑 `pytest` 这类命令需要显式在契约里写，
   且命令前缀白名单（`python` / `python3` / `pytest` / `npm` / `node`）。
3. **P32 是否顺带做前端徽标**：建议第一期只做后端 + CLI 报告，
   前端放 P32.1，先把判定数据跑出来。

## 2. 数据（schema 21 → 22）

`agent_tasks` 只做加法：

| 字段 | 说明 |
|---|---|
| `contract_json` | 任务契约；空 = 老任务，验收为 `skipped` |
| `verdict_state` | `passed` / `failed` / `skipped` / `error`，列表查询用 |
| `verdict_json` | 逐条结果 + 改动文件清单；≤64KB，坏了按 `{}` |

迁移：
- `core/db/schema_agents.py` 的 `CREATE TABLE` 加三列；
- `core/db/migrate.py::_migrate_columns` 对已存在的 `agent_tasks` 补列
  （`PRAGMA table_info(agent_tasks)` 判断，与现有写法一致）；
- `core/db/schema.py` 的 `SCHEMA_VERSION` 21 → 22。

## 3. 契约格式

```json
{
  "v": 1,
  "scope": {
    "roots": ["D:/Desktop/learnsys"],
    "allow_write": false,
    "max_files": 0
  },
  "deliverables": [
    {"kind": "file", "path": "docs/xxx.md"}
  ],
  "acceptance": [
    {"id": "a1", "check": "no_workspace_change"},
    {"id": "a2", "check": "within_scope"},
    {"id": "a3", "check": "file_nonempty", "args": {"path": "docs/xxx.md"}}
  ],
  "on_unverifiable": "fail"
}
```

第一期只支持 4 种检查：

| check | 判什么 | 参数 | 默认挂载 |
|---|---|---|---|
| `no_workspace_change` | 工作区前后快照差集为空 | — | `mode=read` |
| `within_scope` | 所有改动路径在 `scope.roots` 内，且文件数 ≤ `max_files` | `roots` / `max_files` | 两种模式 |
| `file_nonempty` | 指定文件存在且非空 | `path`（相对 workspace） | 不默认 |
| `command_zero` | 命令退出码为 0（超时 ≤120 秒） | `cmd`（数组，白名单前缀） | 不默认 |

**默认契约**（`build_default_contract`）：

- `mode=read` → `no_workspace_change` + `within_scope(max_files=0)`
- `mode=write` → `within_scope(max_files=50)`（常量 `warden.DEFAULT_MAX_FILES`，本期不做配置项）

## 4. 快照与差集（核心技术点）

```text
开始：snapshot(workspace)  →  S0
执行：agent 子进程
结束：snapshot(workspace)  →  S1
变更集 = diff(S0, S1)
```

两种实现，按目录自动选：

| 条件 | 做法 | 注意 |
|---|---|---|
| workspace 是 git 仓库（有 `.git`） | `git status --porcelain=v1 -z` + `git rev-parse HEAD` | **必须前后各取一次再做差**，否则会把用户自己的未提交改动算成 agent 的 |
| 否则 | `os.walk` 记 `path → (size, mtime_ns)` | 排除 `.git`、`.venv`、`node_modules`、`build-*`、`dist*`、`__pycache__` |

**系统痕迹一律排除**：任务结果目录 `DATA_ROOT/学习档案/agents`、数据库文件及其
`-wal/-shm/-journal`。**默认工作目录就是 `DATA_ROOT`**，不排除的话光开库写 WAL
就会被判成「只读任务改动了工作区」。排除是精确路径，不是整个 `DATA_ROOT`——
用户真改了数据目录里的其他文件，仍然会被发现。

**已知限制（写进文档，不藏）**：
- agent 如果自己 `git commit`，工作区前后可能都干净 → 第一期只在 `HEAD` 变化时记为
  `commit_detected` 并判 `failed`（保守），第二期再支持比较 commit 内容。
- 文件 `mtime` 精度在某些文件系统上可能一致 → 同时比 `size`，并接受少量漏判。
- 快照用 `os.scandir` 而不是 `os.walk`+`stat`（Windows 上目录枚举自带 size/mtime）：
  实测 `D:\Desktop` 71,860 个文件从 2.7 秒降到 **0.8 秒**，不触发上限。
  `SNAPSHOT_MAX_FILES` 默认 200,000；真超过即截断并标 `truncated: true`，
  此时判 `error`（不能假装验过）。工作区若是整个盘，会诚实报错而不是假绿。

## 5. 后端改动

| 文件 | 改动 | 预估 |
|---|---|---|
| `services/agents/warden.py` | **新建**：快照、差集、4 种检查、`verify()`、`build_default_contract()` | ~260 行 |
| `services/agents/runner.py` | 启动前 `warden.snapshot(exclude=…)`；`finally` 里 `warden.verify()`，结果并入 `update_agent_task`；结果文件新增「验收」段；`_verdict_exclude()` 排除数据库与结果目录 | +55 行（308 → 363） |
| `store/agent_tasks.py` | `_TASK_COLUMNS` 加 `verdict_state`；`_UPDATE_FIELDS` 加 `contract_json` / `verdict_state` / `verdict_json`；`_task_dict` 加 `verdict_state` 与 `has_contract` | +20 行（360 → ~380） |
| `server/routes_agents.py` | `TaskIn` 加可选 `contract`；建任务时校验并落库；详情接口返回 `verdict` 全文 | +30 行（312 → ~342） |
| `core/db/schema_agents.py` | 加 3 列 | +3 行 |
| `core/db/migrate.py` | `agent_tasks` 补列 | +10 行 |
| `core/db/schema.py` | `SCHEMA_VERSION` 21 → 22 | 1 行 |
| `tools/agent_verify_report.py` | **新建**：CLI 报告，默认只读 | ~120 行 |

**唯一落点**：所有检查逻辑只在 `warden.py`；`runner` / `routes` 只调用，不复制判定规则。

## 6. Verdict 格式

```json
{
  "v": 1,
  "state": "failed",
  "checked_at": "2026-11-05 14:02:11",
  "elapsed_ms": 143,
  "workspace": "D:/Desktop/learnsys",
  "changes": {
    "changed": ["docs/a.md", "learnsys/x.py"],
    "count": 2,
    "truncated": false,
    "commit_detected": false
  },
  "items": [
    {"id": "a1", "check": "no_workspace_change", "expected": "0 个改动",
     "actual": "2 个改动", "ok": false, "detail": "只读任务改动了工作区"},
    {"id": "a2", "check": "within_scope", "expected": "≤0 个文件",
     "actual": "2 个文件", "ok": false, "detail": "越界：learnsys/x.py"}
  ],
  "summary": "0/2 通过"
}
```

`state` 取值：

| state | 含义 |
|---|---|
| `passed` | 全部通过 |
| `failed` | 有红 |
| `skipped` | 没有契约（老任务）或不适用 |
| `error` | 验收自身异常 / 快照截断 / 命令超时 |

## 7. 接口

| 方法 | 路径 | 变化 |
|---|---|---|
| POST | `/api/agents/tasks` | 入参新增可选 `contract`；非法契约 422 |
| GET | `/api/agents/tasks` | 任务多 `verdict_state`、`has_contract`（不返回全文） |
| GET | `/api/agents/tasks/{id}` | 新增 `verdict` 全文 |
| POST | `/api/agents/tasks/{id}/recheck` | **本期不做**：起始快照没有持久化，事后重验会把「任务结束后用户自己的改动」算进去 |

## 8. 前端（P32.1，本期不做）

- 任务卡片徽标：绿「验收 3/3」/ 红「验收 1/3」/ 灰「未验证」
- 详情页「验收」面板：逐条绿红 + 改动文件列表 + 「重新验收」按钮
- 派活表单：高级选项里可填契约（默认折叠，不打扰）

## 9. 测试与验收

### 新增测试（实际 45 条：`test_agent_warden.py` 36 + `_run.py` 3 + `_api.py` 6）

| 类别 | 用例 |
|---|---|
| 快照 | git 仓库前后差集、非 git 目录 walk、排除目录生效、文件数截断 |
| 只读 | 零改动 → passed；改 1 个 → failed |
| 写入 | 3 个文件在范围内 → passed；1 个越界 → failed；超 `max_files` → failed |
| 产物 | 文件存在非空 → passed；空文件 → failed；不存在 → failed |
| 命令 | 退出码 0 → passed；1 → failed；超时 → error；非白名单前缀 → error |
| 自身异常 | workspace 不存在 → error，**不得写 passed** |
| 契约 | 缺字段 / 未知 check → `error` 而不是静默跳过 |
| 兼容 | 无契约老任务 → `skipped`，列表正常 |

### 施工验收（必须先看到证据）

1. 全量测试通过 + `tools/arch_report.py --check` + `tools/layering_report.py`；
2. 生产库**副本**迁移 21 → 22，行数与历史任务数不变；
3. 8766 隔离库真机：派一条只读任务（零改动）→ `passed`；
   手动在工作区改一个文件再派一条 → `failed`；
4. 打包验证 `services.agents.warden` 在 exe 归档里（PyInstaller 静态收集）；
5. `tools/agent_verify_report.py` 输出最近 20 条任务的验收分布。

## 10. 分期

| 期 | 内容 | 说明 |
|---|---|---|
| **P32** | 后端 + 4 种检查 + CLI 报告 | 零模型成本，先把判定数据跑出来 |
| **P32.1** | 前端徽标 / 详情面板 / route 计入 `verdict_state=failed` | 有数据后再动路由 |
| **P32.2** | L1 盲检（独立模型调用，只给契约 + 产物，不给自述） | 按 P32 的失败样本决定要不要做 |

## 11. 口径与限制

- **`done` ≠ 做对了**：本阶段只回答「有没有按契约做完」，不回答「内容对不对」。
  文案统一写「验收通过 / 验收失败」，不写「正确 / 错误」。
- **验收失败不阻断链**：第一期子任务照常放行，避免把现有任务链卡死。
- **不是沙箱**：快照只能发现改动，不能阻止改动；写入边界仍由 `base.build_argv` 保证。
- **数据库内容不在快照里**：`learning.db` 及其 WAL/SHM 已被排除（否则默认工作目录会误报）。
  数据本身的正确性由迁移测试、备份与回滚保证，不归本闸门管。
- **不信任自述**：后续 L1 盲检必须只读产物，禁止把 `result_text` 当证据。
- **体量**：`warden.py` 超过 400 行就按「快照 / 检查 / 契约」拆成子包，
  不要等撞 500 行红线。
