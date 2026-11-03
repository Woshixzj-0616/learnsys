"""答案 vs 证据的规则审核：只出问题清单，不改写、不调模型。

只查**能被本轮证据核对**的事实性断言（链接、命令输出、绝对结论、版本行为），
不做主观质量评价。误伤护栏：
- 普通知识题（`ops=False` 且 `code_debug=False`）不跑；
- `localhost` / `127.0.0.1` / 文件路径不算 URL；
- 用户原话里给过的数字、链接、输出不判「凭记忆」；
- 标了「示例 / 例如 / 预期」的代码块不当成命令输出；
- 一类问题只报一次，最多 5 条，避免重写负担。

重写提示词在 `prompt_ops.py`，这里只做判定。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from learnsys.agent.prompt_ops import REWRITE_SYSTEM, build_rewrite_user

__all__ = ["Issue", "audit", "issue_text", "note_for",
           "REWRITE_SYSTEM", "build_rewrite_user"]


@dataclass(frozen=True)
class Issue:
    kind: str      # fake_url / fake_output / unsupported_absolute / missing_label / doc_without_url
    detail: str
    quote: str = ""


# 链接里不允许出现中文/全角括号：那是「（2026-10）」之类的正文，不是 URL 的一部分。
_URL_RE = re.compile(r"https?://[^\s<>\"'（）()【】\[\]，。；、一-鿿]+")
_LOCAL_PREFIXES = (
    "http://localhost", "https://localhost",
    "http://127.0.0.1", "https://127.0.0.1",
    "http://0.0.0.0", "https://0.0.0.0",
    "http://[::1]", "https://[::1]",
)
_ABS_RE = re.compile(
    r"(根因就是|就是根因|一定是|必然是|必然|官方规定|肯定是|毫无疑问|文档说|官方说)")
# 只认「默认值/版本」的明确断言，别把「默认站点的关键是 listen 80」这类机制讲解误伤。
_VERSION_CLAIM_RE = re.compile(
    r"(?:默认(?:端口|值|配置|行为|路径)?\s*(?:是|为|等于|通常是|一般是)\s*[`'\"]?\d"
    r"|版本\s*(?:是|为|号)?\s*[`'\"]?v?\d+(?:\.\d+)"
    r"|v?\d+\.\d+(?:\.\d+)?\s*(?:版本|发布|起可用))")
_LABEL_WORDS = ("未验证", "凭记忆", "需要你确认", "需要你在机器上", "需要确认",
                "待确认", "不确定")
_DOC_RE = re.compile(r"(官方文档|文档里|文档中|文档说|官方说明)")
# 「退出码」单独出现常是排查建议，不算在报假输出；必须是「输出如下/运行结果」这类交付语气。
_OUTPUT_RE = re.compile(
    r"(?:实际输出|运行结果|执行结果|终端输出|输出结果)\s*(?:如下|是|为|[:：])"
    r"|输出\s*(?:如下|是|为)"
    r"|结果\s*(?:如下|[:：])")
_SOFT_OUTPUT_WORDS = ("示例", "例如", "预期", "应该是", "大概")
_USER_OUTPUT_RE = re.compile(r"(?:输出|报错|结果)\s*(?:如下|是|为|[:：])")
_TRAILING = ".,;:!?'\"。，；：、"


def _urls_in(text: str) -> list[str]:
    return [match.group(0).rstrip(_TRAILING)
            for match in _URL_RE.finditer(str(text or ""))]


def _norm(url: str) -> str:
    return str(url or "").rstrip("/")


def _is_local(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(lowered.startswith(prefix) for prefix in _LOCAL_PREFIXES)


def _is_placeholder(url: str) -> bool:
    """`http://IP:端口/路径` 这种模板不是「编造的链接」。"""
    lowered = str(url or "").lower()
    return any(token in lowered for token in
               ("://ip", "://your", "example.com", "example.org", "example.net"))


def _quote_line(text: str, start: int, limit: int = 60) -> str:
    end = text.find("\n", start)
    if end < 0:
        end = len(text)
    return text[start:end].strip()[:limit]


def _has_results(evidence) -> bool:
    return bool(getattr(evidence, "results", None))


def _has_tool(evidence, name: str) -> bool:
    checker = getattr(evidence, "has_tool", None)
    return bool(checker(name)) if callable(checker) else False


def audit(answer: str, evidence, user_text: str = "", *,
          ops: bool = False, code_debug: bool = False) -> list[Issue]:
    """返回问题清单；空列表 = 通过。只在 ops / code_debug 时跑。"""
    if not (ops or code_debug):
        return []
    text = str(answer or "")
    if not text.strip():
        return []

    issues: list[Issue] = []
    reported: set[str] = set()

    def add(issue: Issue) -> None:
        if issue.kind in reported or len(issues) >= 5:
            return
        reported.add(issue.kind)
        issues.append(issue)

    evidence_urls = {_norm(url) for url in
                     (getattr(evidence, "urls", lambda: set())() or set())}
    user_urls = {_norm(url) for url in _urls_in(user_text)}

    for url in _urls_in(text):
        if (_is_local(url) or _is_placeholder(url)
                or _norm(url) in evidence_urls or _norm(url) in user_urls):
            continue
        add(Issue("fake_url", "答案里的链接不在本轮证据或用户原话里", url))
        break

    if (not _has_tool(evidence, "run_code") and "```" in text
            and not _USER_OUTPUT_RE.search(str(user_text or ""))):
        match = _OUTPUT_RE.search(text)
        if match:
            window = text[max(0, match.start() - 20):match.start()]
            nearby = "```" in text[match.end():match.end() + 200]
            if nearby and not any(word in window for word in _SOFT_OUTPUT_WORDS):
                add(Issue("fake_output",
                          "答案给出了命令输出，但本轮没有 run_code 证据，用户也没提供输出",
                          _quote_line(text, match.start())))

    if ops and not _has_results(evidence):
        match = _ABS_RE.search(text)
        if match:
            add(Issue("unsupported_absolute",
                      "本轮没有工具证据，却把候选说成了根因/定论",
                      _quote_line(text, match.start())))

    if (ops and not _has_results(evidence)
            and not any(word in text for word in _LABEL_WORDS)):
        match = _VERSION_CLAIM_RE.search(text)
        if match:
            digits = re.findall(r"\d+", match.group(0))
            if not digits or not all(digit in str(user_text or "") for digit in digits):
                add(Issue("missing_label",
                          "答案给了版本/默认行为的断言，但没有证据也没有「未验证」标记",
                          _quote_line(text, match.start())))

    if _DOC_RE.search(text) and not _urls_in(text) and not evidence_urls:
        match = _DOC_RE.search(text)
        add(Issue("doc_without_url",
                  "声称来自官方文档，但没有给出打开过的链接",
                  _quote_line(text, match.start())))

    return issues


def issue_text(issue: Issue) -> str:
    text = f"{issue.kind}：{issue.detail}"
    return f"{text}（{issue.quote}）" if issue.quote else text


def note_for(issues) -> str:
    """重写后仍有问题时，贴在答案末尾的显式清单（不假装通过）。"""
    if not issues:
        return ""
    lines = "\n".join(f"- {issue_text(issue)}" for issue in issues)
    return ("\n\n> **未核实项**：以下内容本轮没有证据支持，"
            "请对照实际情况确认：\n" + lines)
