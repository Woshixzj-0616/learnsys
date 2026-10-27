"""自检：回答里的引用必须来自本轮工具结果。

只做**可核对**的检查（资料 id/页码、错题编号、记录时间），不做主观质量评价：
- 工具没读过的资料、没出现过的页码、没查过的错题编号 → 问题；
- 没调用任何工具却声称「资料里说 / 记录里提到」→ 问题；
- 普通知识回答不要求引用，不误伤。

自检不通过时，loop 用快模型按问题清单重写一次；仍不通过就在答案里明示。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MATERIAL_RE = re.compile(
    r"【资料\s*(\d+)\s*[：:]([^】]*?)"
    r"(?:\s*·\s*第\s*([0-9、,，和\-–~至\s]+?)\s*页)?】")
PAGE_RANGE_RE = re.compile(r"第\s*(\d+)(?:\s*[–\-~至]\s*(\d+))?\s*页")
WRONG_RE = re.compile(r"错题[本]?\s*[#＃]\s*(\d+)")
STAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})")
ANSWER_STAMP_RE = re.compile(
    r"\[(?:问答|课堂转写|屏幕文字)?\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]")
CLAIM_RE = re.compile(
    r"(资料|记录|错题本)[^。！？\n]{0,10}(说|提到|显示|写着|有|记载|表明|指出|说法)")

REWRITE_SYSTEM = """你是学习工作台的校对员。用户会给你一份草稿、以及本轮工具实际返回的证据。
你的任务：只修正草稿里**无法由证据支持**的引用和说法，其余内容、结构、语气尽量保持原样。

规则：
- 证据里没有的资料 id、页码、错题编号、记录时间，必须删掉或改成证据里的真实值；
- 不能为了「看起来有来源」而编造新的引用；
- 证据支持的内容可以保留；普通知识（不声称来自本地资料/记录）不用改动；
- 保留草稿里的原有结构标记（【第N题】【批改】【知识点】）以及「【批改】正确/错误」
  的判定，不要改写这些标记或对错结论；
- **保持草稿原有篇幅，不扩写，不新增代码块，不在结尾追加提问**；
- 直接输出修正后的完整答案（Markdown），不要解释你改了什么。"""


def _pages(spec: str) -> set[int]:
    """把「1、2」「3–5」「第 7 页」这类写法拆成页码集合。"""
    pages: set[int] = set()
    for match in re.finditer(r"(\d+)\s*(?:[–\-~至]\s*(\d+))?", str(spec or "")):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if start <= end and end - start <= 50:
            pages.update(range(start, end + 1))
        else:
            pages.add(start)
    return pages


@dataclass
class Evidence:
    """本轮工具结果的账本：只记能被回答引用的东西。"""
    results: list[dict] = field(default_factory=list)
    material_pages: dict[int, set[int]] = field(default_factory=dict)
    material_titles: dict[int, str] = field(default_factory=dict)
    wrong_ids: set[int] = field(default_factory=set)
    stamps: set[str] = field(default_factory=set)

    def add(self, name: str, args: dict, content: str) -> None:
        text = str(content or "")
        self.results.append({"name": str(name or ""), "content": text[:20000]})
        for match in MATERIAL_RE.finditer(text):
            material_id = int(match.group(1))
            title = (match.group(2) or "").strip()
            page_spec = match.group(3)
            pages = self.material_pages.setdefault(material_id, set())
            if page_spec:
                pages.update(_pages(page_spec))
            if title:
                self.material_titles.setdefault(material_id, title)
        if name == "read_material":
            try:
                material_id = int((args or {}).get("material_id") or 0)
            except (TypeError, ValueError):
                material_id = 0
            if material_id:
                pages = self.material_pages.setdefault(material_id, set())
                head = re.match(r"【([^】]+)】", text)
                if head:
                    self.material_titles.setdefault(material_id, head.group(1).strip())
                for match in PAGE_RANGE_RE.finditer(text[:200]):
                    pages.update(_pages(match.group(0)))
        for match in WRONG_RE.finditer(text):
            self.wrong_ids.add(int(match.group(1)))
        if name in ("save_wrongbook", "save_training_error"):
            # 写入类工具返回「已收进…（#12）」，没有「错题 #12」字样；
            # 把返回的编号也算成已核对，免得自检把刚写入的卡片判成编造。
            for match in re.finditer(r"[#＃]\s*(\d+)", text):
                self.wrong_ids.add(int(match.group(1)))
        for match in STAMP_RE.finditer(text):
            self.stamps.add(match.group(1))

    def digest(self, limit: int = 7000) -> str:
        """给重写模型看的证据摘要（截断，不把整库塞进去）。"""
        if not self.results:
            return "（本轮没有工具结果）"
        lines = []
        total = 0
        for item in self.results:
            piece = f"【工具 {item['name']}】\n{item['content'][:1600]}"
            if total + len(piece) > limit:
                lines.append("（证据较多，后面省略）")
                break
            lines.append(piece)
            total += len(piece)
        return "\n\n".join(lines)


def verify(answer: str, evidence: Evidence) -> list[str]:
    """返回自检问题清单；空列表 = 通过。"""
    text = str(answer or "")
    issues: list[str] = []
    seen: set[str] = set()

    def add(issue: str) -> None:
        if issue not in seen:
            seen.add(issue)
            issues.append(issue)

    for match in MATERIAL_RE.finditer(text):
        material_id = int(match.group(1))
        cited = _pages(match.group(3) or "")
        if material_id not in evidence.material_pages:
            add(f"引用了本轮没读过的资料 #{material_id}")
            continue
        if cited:
            known = evidence.material_pages.get(material_id) or set()
            if not known:
                add(f"资料 #{material_id} 的页码无法从工具结果核对"
                    "（工具结果里没有页码）")
                continue
            for page in sorted(cited):
                if page not in known:
                    available = "、".join(str(item) for item in sorted(known))
                    add(f"资料 #{material_id} 的第 {page} 页不在工具结果里"
                        f"（读到的是第 {available} 页）")

    for match in WRONG_RE.finditer(text):
        item_id = int(match.group(1))
        if item_id not in evidence.wrong_ids:
            add(f"错题 #{item_id} 不在本轮的错题查询结果里")

    for match in ANSWER_STAMP_RE.finditer(text):
        stamp = match.group(1)
        if stamp not in evidence.stamps:
            add(f"引用的记录时间 {stamp} 不在本轮工具结果里")

    if not evidence.results and CLAIM_RE.search(text):
        add("回答声称来自本地资料/记录，但本轮没有调用任何工具")

    return issues


def build_rewrite_user(answer: str, issues: list[str], digest: str) -> str:
    """重写请求：草稿 + 问题清单 + 工具证据。"""
    problems = "\n".join(f"- {issue}" for issue in issues) or "（无）"
    return ("【待修正的草稿】\n" + answer.strip()
            + "\n\n【自检发现的问题】\n" + problems
            + "\n\n【本轮工具实际返回的证据】\n" + digest
            + "\n\n请直接输出修正后的完整答案。")


def note_for(issues: list[str]) -> str:
    """重写后仍不通过时，贴在答案末尾的显式提示。"""
    if not issues:
        return ""
    lines = "\n".join(f"- {issue}" for issue in issues)
    return "\n\n> **自检提示**：以下引用无法由本轮工具结果核对，请对照原文确认：\n" + lines
