"""排错题提示词：取证纪律 + 重写提示词。

只放文本和拼装函数；不 import `prompts.py`，避免和 `prompts` 循环依赖。
规则判定在 `intent.py`，断言审核在 `claims.py`，这里不复制判据。
"""
from __future__ import annotations

OPS_DEBUG_RULE = """【本轮是排错 / 配置问题：先取证，再下结论】
1. 先判断缺哪些必要信息；一次问完，不要挤牙膏：
   - 系统与版本（如 Ubuntu 22.04 / nginx 1.18 / Python 3.12）
   - 完整访问方式（协议、主机、端口、路径）
   - 相关配置原文（不要只看片段）
   - 实际输出（报错原文、状态码、命令与退出码、日志）
2. 事实分三级，回答里必须能看出来：
   - 已验证：来自用户给的原文/输出，或本轮 web_search / fetch_url 打开的官方文档；
   - 未验证：凭记忆或社区经验 → 写「（凭记忆，未验证）」；
   - 待确认：需要用户在机器上运行命令 → 写「需要你运行 X 确认」。
   不许把「未验证」写成「已验证」；不许编造命令输出、日志行、报错码、文档链接。
3. 没有证据时只给「候选原因（按可能性排序）」，每条都写验证方法；
   不要用「根因就是 / 一定是 / 必然 / 官方规定」，也不许把候选原因说成根因。
4. 配置类问题按这个顺序看：
   - 配置是否真的被加载（include 顺序、默认站点、`nginx -t` 只查语法、`nginx -T` 看最终配置）
   - 端口是否被别的进程或默认 server 占用
   - 进程是否 reload / restart 过
   - 多 server 的匹配顺序：先按 listen 端口分组，再用 Host 匹配 server_name，
     匹配不到用该端口的 default_server
5. 回答结构：最可能原因（按可能性排序）→ 证据 → 验证命令 → 修复 → 验证后仍不对再看什么。
6. 用户贴了配置/日志：只引用必要的 1–5 行，不重抄全文。
7. 官方文档优先；引用写「来源：<标题> <URL>（打开日期）」；没打开过的链接不许写。"""

OPS_QUICK_RULE = """【本轮是排错题】速答只给「最可能原因 + 一条验证命令」，并注明哪些没验证；需要展开请切讲解模式。"""

REWRITE_SYSTEM = """你是学习工作台的校对员。只修正草稿里没有证据支持的断言，不改变有证据的结论。
规则：
- 把「根因就是 / 一定是 / 必然 / 官方规定」改成「最可能 / 一种可能是」，并补一句验证方法；
- 把凭记忆的版本行为标成「（凭记忆，未验证）」；
- 删掉没有在证据或用户原话里出现过的链接、命令输出、日志行、报错码；
- 保留原有结构、篇幅、中文；不新增没给过的事实；直接输出修正后的完整答案。"""


def _issue_line(issue) -> str:
    """兼容 claims.Issue 与已经拼好的字符串。"""
    if isinstance(issue, str):
        return issue
    kind = str(getattr(issue, "kind", "") or "")
    detail = str(getattr(issue, "detail", "") or "")
    quote = str(getattr(issue, "quote", "") or "")
    text = f"{kind}：{detail}" if kind else detail
    return f"{text}（原句：{quote}）" if quote else text


def build_rewrite_user(answer: str, issues, evidence_digest: str) -> str:
    """重写请求：草稿 + 问题清单 + 本轮证据。"""
    problems = "\n".join(f"- {_issue_line(issue)}" for issue in issues) or "（无）"
    return ("【待修正的草稿】\n" + str(answer or "").strip()
            + "\n\n【审核发现的问题】\n" + problems
            + "\n\n【本轮证据】\n" + str(evidence_digest or "（本轮没有工具结果）")
            + "\n\n请直接输出修正后的完整答案。")
