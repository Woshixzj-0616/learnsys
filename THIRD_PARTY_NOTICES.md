# 第三方组件与许可证

本项目以 MIT License 发布。以下是运行时依赖与前端 vendor 的说明；完整许可证文本以各项目仓库为准。

## 前端（`web/vendor/`，许可证文本在 `web/vendor/licenses/`）

| 组件 | 用途 | 许可证 |
| --- | --- | --- |
| marked | Markdown 解析 | MIT |
| DOMPurify | HTML 消毒 | Apache-2.0 / MPL-2.0 双许可 |
| highlight.js | 代码高亮（含 dark 主题） | BSD-3-Clause |
| KaTeX | 数学公式（含字体） | MIT |

前端依赖全部本地打包，不请求 CDN。

## Python 运行时

| 组件 | 用途 | 许可证 |
| --- | --- | --- |
| PySide6 / Qt for Python | 原生快捷栏 | LGPL-3.0（Qt 部分） |
| FastAPI / Starlette / Uvicorn / Pydantic | 本地 HTTP 服务 | MIT / BSD-3-Clause |
| httpx | 测试与连接检查 | BSD-3-Clause |
| faster-whisper / ctranslate2 / onnxruntime | 本地语音转写 | MIT / Apache-2.0 |
| pyaudiowpatch / pycaw / comtypes | Windows 音频回环与系统接口 | MIT / Apache-2.0 |
| PyMuPDF / python-docx / python-pptx | 文档抽取 | AGPL-3.0 / MIT |
| RapidOCR | 图片文字兜底 | Apache-2.0 |

> PyMuPDF 是 AGPL-3.0：如果分发修改版并对外提供服务，请先确认合规；本项目默认只在本地个人使用。

## 不随仓库分发

- Whisper 模型、六级真题音频、`learning.db`、设置文件、截图/录音。
- 发布包请附 SHA256，并确保不包含上述个人数据。
