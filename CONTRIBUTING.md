# 贡献指南

## 先跑起来

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py"
.venv\Scripts\python -m learnsys.server.app
```

打开 `http://127.0.0.1:8765/`。只改 Web 工作台时不需要启动 Qt 托盘。

## 代码结构

| 目录 | 放什么 |
| --- | --- |
| `learnsys/agent/` | Agent 循环、Provider、工具、提示词（直连 Anthropic Messages 兼容服务） |
| `learnsys/ask/` | 原生快捷栏、录制、OCR、电脑助手、启动链路 |
| `learnsys/server/` | FastAPI：Agent、数据、设置、上传、六级、插件清单 |
| `learnsys/plugins/<id>/plugin.json` | 插件清单（唯一来源） |
| `web/` | 工作台：壳层、原生页、样式、本地 vendor |
| `tests/` | 单元 / 接口 / 迁移 / 状态机回归 |

## 提交前

- 全量测试：`python -m unittest discover -s tests -p "test_*.py"` 全绿。
- 改前端：打开相关页面，控制台 0 error；至少走一遍关键路径。
- 加插件：按 [`docs/插件开发规范.md`](docs/插件开发规范.md)，并在 `tests/test_plugins.py` 补清单/事件测试。
- 不提交：`设置.json`、`learning.db`、截图/录音、模型、真题音频、任何密钥。

## 提交信息

用一句中文说清「改了什么 + 为什么」，正文列关键点。一次提交只做一件事；
重构和功能改动尽量分开，方便回滚。
