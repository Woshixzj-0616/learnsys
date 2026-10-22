"""通用文本服务：解释 / 摘要。

和翻译一样只走一条模型调用路径（`agent.provider_anthropic`），
不在 services 里另写一套 HTTP。查词（define）直接复用 `translate`，
因为它本来就是「带音标和释义的单词翻译」。
"""
from __future__ import annotations

from learnsys.agent import provider_anthropic
from learnsys.agent.config import load_config

MAX_INPUT = 12000

SYSTEMS = {
    "explain": (
        "你是学习助手。用中文解释用户给出的句子或概念：先给一句话结论，"
        "再拆开讲为什么，最后指出容易混淆的地方。不要编造原文没有的信息；"
        "拿不准就直说。"),
    "summarize": (
        "你是学习助手。用中文把用户给的内容压缩成要点：最多 7 条，"
        "每条一行，保留数字、定义和因果关系。不添加原文没有的结论。"),
}


def complete(kind: str, text: str, context: str = "") -> dict:
    """单轮调用模型；返回 {text, model, kind}。失败抛中文异常，由路由转 500。"""
    system = SYSTEMS.get(kind)
    if system is None:
        raise ValueError(f"没有这个文本服务：{kind}")
    body = str(text or "").strip()
    if not body:
        raise ValueError("text 不能为空")
    config = load_config()
    if not config.ready:
        raise RuntimeError("还没配置模型：到设置里填地址和密钥后再试。")
    extra = str(context or "").strip()
    user = body[:MAX_INPUT]
    if extra:
        user = f"【上下文】{extra[:2000]}\n\n【内容】\n{user}"
    messages = [{"role": "user", "content": [{"type": "text", "text": user}]}]
    parts: list[str] = []
    result = None
    for event in provider_anthropic.stream_messages(config, system, messages, None):
        if event.kind == "text":
            parts.append(event.text)
        elif event.kind == "done":
            result = event.result
    answer = (result.text if result is not None and result.text
              else "".join(parts)).strip()
    if not answer:
        raise RuntimeError("模型没有返回内容，稍后重试。")
    return {"text": answer, "model": config.model, "kind": kind}
