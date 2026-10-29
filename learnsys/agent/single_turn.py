"""单轮模型调用的窄接口：给 services 用，不带工具、不拼上下文。

五个服务（翻译 / 六级分析 / 训练批改 / 录像分析 / 每日简报）原本各自
复制同一段 `AgentRequest + 遍历事件` 的循环；统一走这里，将来把单轮
调用拆出 agent 时只改一个文件。

返回 `(文本, 错误, usage)`，与调用方原来的三元组一致。
"""
from __future__ import annotations

from learnsys.agent.turn import AgentRequest


def complete(prompt: str, *, system_override: str = "", cfg=None,
             abort=None, mode: str = "quick",
             use_tools: bool = False) -> tuple[str, str, dict]:
    """跑一轮模型调用，返回 (文本, 错误, usage)；异常折成中文错误串。

    `run` 在调用时从包属性取（不在导入时绑定），这样测试继续可以
    `mock.patch.object(agent, "run", ...)` 打桩，不用改到内部模块。
    """
    from learnsys import agent as agent_pkg

    text, error, usage = "", "", {}
    request = AgentRequest(prompt, system_override=system_override,
                           use_tools=use_tools, mode=mode)
    try:
        for event in agent_pkg.run(request, cfg=cfg, abort=abort):
            if event.kind == "done":
                text = str(event.data.get("text") or "")
                usage = event.data.get("usage") or {}
            elif event.kind == "error":
                error = str(event.text or "模型调用失败")
    except Exception as exc:  # noqa: BLE001 —— 调用方统一按错误串展示
        error = str(exc) or "模型调用失败"
    return text, error, usage
