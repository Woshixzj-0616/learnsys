# P15 · MCP 只读

> 2026-10-21。对应 `00-阶段总览.md` 的 P15：5 个只读工具，供 Claude Code / Codex 接入。
> **原则**：外部客户端能读学习数据，不能写；翻译只读缓存/不落学习记录。

## 1. 形态

一个 **stdio MCP 服务**：`python -m learnsys.mcp_server`。

- 不自带数据库连接、不复制业务逻辑：每次工具调用走本机 HTTP `127.0.0.1:8765`，
  和网页/快捷栏用同一套实现。
- 令牌从 `/api/health` 取；`403` 时刷新一次令牌再重试。
- 后台没启动时返回中文错误，不抛栈。
- 日志一律写 stderr；stdout 只放 JSON-RPC。

## 2. 工具（5 个）

| 工具 | 参数 | 数据来源 | 只读 |
|---|---|---|---|
| `study_context` | 无 | `/api/overview` + `/api/today` + `/api/review/stats` | 是 |
| `search_materials` | `query`、`limit=5` | `/api/materials?q=` | 是 |
| `read_material` | `material_id`、`offset=0`、`limit=4000` | `/api/materials/{id}?body=1` | 是 |
| `due_reviews` | `limit=20` | `/api/review/queue` | 是 |
| `translate` | `text`、`kind=word` | `/api/services/translate` | 否（只写翻译缓存） |

`translate` 可能在 `service_results` 里留下缓存与流水，但**不写问答、错题、进度**；
工具说明里写清楚，`annotations.readOnlyHint=false`。其余四个 `readOnlyHint=true`。

## 3. 协议

- stdio，逐行 JSON-RPC 2.0。
- 方法：`initialize`、`notifications/initialized`（不应答）、`tools/list`、`tools/call`、`ping`。
- `initialize` 返回 `protocolVersion: "2024-11-05"`、`capabilities.tools`、`serverInfo`。
- 工具结果：`{"content":[{"type":"text","text":"…"}],"isError":false}`；
  后台不可用等错误用 `isError:true` + 中文说明。
- 未知方法 `-32601`，坏 JSON `-32700`，工具参数错误 `-32602`。

## 4. 文件

| 文件 | 内容 |
|---|---|
| `learnsys/mcp_server.py` | 协议循环 + 5 个工具 + HTTP 客户端 |
| `tests/test_mcp_server.py` | 协议、工具清单、参数校验、用 mock 证明调用路径 |
| `docs/MCP接入.md` | Claude Code / Codex 的配置示例（占位路径，不写个人绝对路径） |

## 5. 测试

- `initialize` 返回协议的三个字段。
- `tools/list` 正好 5 个，四个 `readOnlyHint=true`，`translate=false`。
- 每个工具：mock HTTP 返回固定数据，断言 `content[0].text` 含关键字段。
- 未知工具/未知方法/坏参数分别返回对应错误码。
- `notifications/initialized` 不产生响应。

## 6. 验收

1. 全量测试通过（当前 405 + 新增）。
2. 真实进程：`python -m learnsys.mcp_server` 发 `initialize` → `tools/list` → `due_reviews`，
   三条都有响应；`due_reviews` 返回真实库结果（当前为空也要正常回「没有到期」）。
3. 后台关闭时，工具返回中文错误而不是崩。
4. 一个 commit；不 push、不发版。
