"""六级写作/翻译训练底座（P24.1）。

纯逻辑包：不依赖 services / agent / ask / server。
- `content`  内容包加载与句子派生
- `validate` 内容结构校验（工具与测试共用）
- `rubric`   评分档位、硬规则、模板检测的唯一落点
- `prompts`  三类批改提示词
- `review`   模型输出校验：quote 过滤、档位钳制、多次取中位

模型调用与任务队列在 `services.train_review`。
"""
from __future__ import annotations

__all__ = ["content", "validate", "rubric", "prompts", "review"]
