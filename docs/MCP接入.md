# 接入 MCP（只读）

> P15 起。学习工作台提供一个 stdio MCP 服务，让 Claude Code / Codex 读取学习数据。
> **只读**：不写问答、错题、进度；`translate` 只写翻译缓存。

## 1. 先决条件

- 学习工作台后台正在运行（`127.0.0.1:8765`）。
- 用仓库自带的 Python：`<仓库>\.venv\Scripts\python.exe`。
- 不需要打包 exe；MCP 服务直接跑源码。

## 2. 五个工具

| 工具 | 作用 |
|---|---|
| `study_context` | 今日学习点、连续天数、问答/转写/专注、待复习、六级断点 |
| `search_materials` | 资料库检索（标题、页码、片段） |
| `read_material` | 按 id 读资料正文，支持 offset/limit 分页 |
| `due_reviews` | 今天到期的错题/生词（FSRS） |
| `translate` | 单词/句子/整段翻译 |

## 3. Claude Code

项目根目录建 `.mcp.json`（路径换成你的仓库）：

```json
{
  "mcpServers": {
    "learnsys": {
      "command": "D:\\Desktop\\learnsys\\.venv\\Scripts\\python.exe",
      "args": ["-m", "learnsys.mcp_server"],
      "env": {
        "PYTHONPATH": "D:\\Desktop\\learnsys",
        "LEARNSYS_MCP_URL": "http://127.0.0.1:8765"
      }
    }
  }
}
```

也可以用命令行注册：

```bat
claude mcp add learnsys -- "D:\Desktop\learnsys\.venv\Scripts\python.exe" -m learnsys.mcp_server
```

注册后在 Claude Code 里用 `/mcp` 确认 `learnsys` 已连接。

## 4. Codex

`~/.codex/config.toml`：

```toml
[mcp_servers.learnsys]
command = 'D:\Desktop\learnsys\.venv\Scripts\python.exe'
args = ["-m", "learnsys.mcp_server"]
startup_timeout_sec = 30
[mcp_servers.learnsys.env]
PYTHONPATH = 'D:\Desktop\learnsys'
LEARNSYS_MCP_URL = "http://127.0.0.1:8765"
```

用 `codex mcp list` 确认。2.12.0 起本机已注册（`learnsys` 显示 enabled）。

## 5. 排错

| 现象 | 原因 |
|---|---|
| 工具返回「后台没有响应」 | 学习工作台没启动，先双击 `学习工作台.cmd` |
| 启动即退出，提示 `No module named learnsys` | `PYTHONPATH` 没指向仓库根目录 |
| 403 | 令牌会从 `/api/health` 自动刷新；仍然 403 就重启后台 |
| 想改端口 | 设 `LEARNSYS_MCP_URL` |

日志一律在 stderr；stdout 只放 JSON-RPC，别往里打印调试信息。

## 6. 写工具评估（2026-10-27，P25.2）

**结论：MCP 继续只读，本轮不加写工具。**

原因：

1. MCP 客户端（Claude Code / Codex）没有工作台的确认弹窗，写操作缺少人工闸门；
2. 用 `confirm=true` 参数代替确认，等于模型自己给自己授权，不满足 P16.1 的确认口径；
3. 工作台已有完整确认链路（`CONFIRM_TOOLS` + 120 秒弹窗），MCP 的价值在读上下文。

若后续要做，只接受「提议箱」形态：MCP 写操作只落 `pending_actions` 表，工作台插件页逐条确认后
才真正执行；留到 P25.3 评估，不在 2.35.0。
