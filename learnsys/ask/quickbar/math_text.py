"""Qt 快捷栏的公式兜底：把 LaTeX 近似翻译成可读的 Unicode 文本。

为什么需要这一层：
- 网页端有 KaTeX；原生快捷栏是 `QTextBrowser + QTextDocument.setMarkdown`，
  Qt 不认 `$...$`，会把 `$H(K)=3K \\bmod 11$` 原样露出来。
- 这里不追求排版保真，只保证「课堂上能读懂、能复制」；复杂矩阵/多行环境
  降级成线性文本，不吐反斜杠。

边界：
- 按行状态机跳过 ``` / ~~~ 围栏和行内反引号，未闭合围栏也不会误伤；
- 只转闭合的 `$...$`、`$$...$$`、`\\(...\\)`、`\\[...\\]`；
- 货币 `$5`、`$5 and $10`、`\\$` 转义不转。
"""
from __future__ import annotations

import re

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ",
    "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ",
    "Omega": "Ω",
}

_SYMBOLS = {
    # 关系 / 运算
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "sim": "∼", "equiv": "≡", "times": "×", "cdot": "·",
    "div": "÷", "pm": "±", "mp": "∓", "ast": "∗", "star": "⋆", "circ": "°",
    "bmod": " mod ", "mod": " mod ", "pmod": " (mod ",
    # 箭头
    "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒",
    "Leftarrow": "⇐", "leftrightarrow": "↔", "iff": "⇔",
    # 集合
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆",
    "supset": "⊃", "supseteq": "⊇", "cup": "∪", "cap": "∩", "emptyset": "∅",
    # 大符号 / 微积分
    "sum": "∑", "prod": "∏", "int": "∫", "iint": "∬", "partial": "∂",
    "nabla": "∇", "infty": "∞", "forall": "∀", "exists": "∃",
    # 括号
    "lceil": "⌈", "rceil": "⌉", "lfloor": "⌊", "rfloor": "⌋",
    "langle": "⟨", "rangle": "⟩",
    # 几何 / 杂项
    "angle": "∠", "perp": "⊥", "parallel": "∥", "ldots": "…", "dots": "…",
    "cdots": "…", "quad": " ", "qquad": "  ",
    # 函数名（保留文字）
    "log": "log", "ln": "ln", "lg": "lg", "exp": "exp", "sin": "sin",
    "cos": "cos", "tan": "tan", "cot": "cot", "sec": "sec", "csc": "csc",
    "arcsin": "arcsin", "arccos": "arccos", "arctan": "arctan",
    "max": "max", "min": "min", "lim": "lim", "sup": "sup", "inf": "inf",
    "det": "det", "gcd": "gcd",
}

# 命令名长的先匹配，避免 `\\le` 被 `\\l` 之类的短名截胡。
_COMMANDS = sorted({**_GREEK, **_SYMBOLS}, key=len, reverse=True)

_SUP = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵",
    "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻",
    "=": "⁼", "(": "⁽", ")": "⁾", "n": "ⁿ", "i": "ⁱ", "x": "ˣ",
    "y": "ʸ", "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ",
    "k": "ᵏ", "m": "ᵐ", "p": "ᵖ", "t": "ᵗ", "u": "ᵘ", "v": "ᵛ",
}
_SUB = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅",
    "6": "₆", "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋",
    "=": "₌", "(": "₍", ")": "₎", "a": "ₐ", "e": "ₑ", "h": "ₕ",
    "i": "ᵢ", "j": "ⱼ", "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ",
    "o": "ₒ", "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ",
    "v": "ᵥ", "x": "ₓ",
}

_MATH_RE = re.compile(
    r"(?<!\\)\$\$(.+?)(?<!\\)\$\$"
    r"|\\\[(.+?)\\\]"
    r"|(?<!\\)\$([^$\n]+?)(?<!\\)\$"
    r"|\\\(([^\n]+?)\\\)",
    re.DOTALL,
)
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


def render(text: str) -> str:
    """把一段 Markdown 里的公式换成 Unicode 近似；代码围栏/行内代码不动。"""
    lines = str(text or "").splitlines(keepends=True)
    out: list[str] = []
    fence = ""
    for line in lines:
        stripped = line.lstrip()
        fence_hit = _FENCE_RE.match(stripped)
        if fence:
            if fence_hit and fence_hit.group(1)[0] == fence:
                fence = ""
            out.append(line)
            continue
        if fence_hit:
            fence = fence_hit.group(1)[0]
            out.append(line)
            continue
        out.append(_render_line(line))
    return "".join(out)


def _render_line(line: str) -> str:
    """处理一行正文；行内反引号里的内容原样保留。"""
    parts = re.split(r"(`+[^\n]*?`+)", line)
    for index, part in enumerate(parts):
        if not part or part.startswith("`"):
            continue
        parts[index] = _render_segment(part)
    return "".join(parts)


def _render_segment(segment: str) -> str:
    def replace(match: re.Match) -> str:
        display = match.group(1)
        bracket = match.group(2)
        inline = match.group(3)
        paren = match.group(4)
        if display is not None:
            body = display
        elif bracket is not None:
            body = bracket
        elif inline is not None:
            if not _looks_math(inline):
                return match.group(0)
            body = inline
        else:
            body = paren or ""
            if not body.strip():
                return match.group(0)
        converted = _latex_to_text(body)
        return converted if converted.strip() else match.group(0)

    return _MATH_RE.sub(replace, segment).replace("\\$", "$")


def _looks_math(body: str) -> bool:
    """行内 `$...$` 的保守判定：宁可不转，也别把货币句吃掉。"""
    value = str(body or "").strip()
    if not value or "\n" in value:
        return False
    # 有反斜杠 = 明确 LaTeX；`\text{中文}` 也走这里。
    if "\\" in value:
        return True
    # 上下标/花括号 = 明确数学。
    if any(char in value for char in "^_{}"):
        return True
    # 纯数字/货币：不转。
    if re.fullmatch(r"[0-9.,]+", value):
        return False
    # 单个变量，或带下标的变量，如 x / n_1。
    if re.fullmatch(r"[A-Za-z]", value):
        return True
    if re.fullmatch(r"[A-Za-z][_^][A-Za-z0-9]+", value):
        return True
    # 含比较/运算符，并且有字母或数字：当作公式。
    if re.search(r"[=<>≤≥±×÷≠≈]", value) and re.search(r"[A-Za-z0-9]", value):
        return True
    # 纯字母/空格（log n、sin x 这类）：短且没有中文，才当公式。
    if len(value) <= 24 and not re.search(r"[一-鿿]", value) \
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9 ()+\-*/.^_]*", value):
        return True
    return False


def _read_group(text: str, index: int) -> tuple[str, int]:
    """读一个参数：`{...}`（支持嵌套）或单个字符。"""
    if index >= len(text):
        return "", index
    if text[index] != "{":
        return text[index], index + 1
    depth = 0
    for pos in range(index, len(text)):
        char = text[pos]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[index + 1:pos], pos + 1
    return text[index + 1:], len(text)  # 没闭合：把剩余内容当参数


def _map_script(value: str, table: dict[str, str]) -> str | None:
    mapped = "".join(table.get(char, "") for char in value)
    return mapped if mapped and len(mapped) == len(value) else None


def _need_parens(value: str) -> bool:
    return any(char in value for char in " +-*/=<>≤≥±×÷")


def _fraction(num: str, den: str) -> str:
    num = num.strip() or "?"
    den = den.strip() or "?"
    if _need_parens(num):
        num = f"({num})"
    if _need_parens(den):
        den = f"({den})"
    return f"{num}/{den}"


def _sqrt(index: str, body: str) -> str:
    body = body.strip()
    if index.strip() == "3":
        return f"∛({body})"
    if index.strip() == "4":
        return f"∜({body})"
    if index.strip():
        return f"√[{index.strip()}]({body})"
    return f"√({body})"


def _latex_to_text(source: str) -> str:
    text = str(source or "")
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            if index + 1 >= len(text):
                index += 1
                continue
            two = text[index + 1]
            if two == "\\":
                out.append("；")
                index += 2
                continue
            if two in " ,;:!":
                out.append(" " if two != "!" else "")
                index += 2
                continue
            if two in "%$&#_{}":
                out.append(two)
                index += 2
                continue
            if two == "√":
                out.append("√")
                index += 2
                continue
            match = re.match(r"[A-Za-z]+", text[index + 1:])
            name = match.group(0) if match else two
            index += 1 + len(name)
            if name in ("text", "mathrm", "mathbf", "mathit", "operatorname"):
                body, index = _read_group(text, index)
                out.append(body)
                continue
            if name == "frac":
                left, index = _read_group(text, index)
                right, index = _read_group(text, index)
                out.append(_fraction(_latex_to_text(left), _latex_to_text(right)))
                continue
            if name == "sqrt":
                root = ""
                if index < len(text) and text[index] == "[":
                    close = text.find("]", index)
                    if close >= 0:
                        root = text[index + 1:close]
                        index = close + 1
                body, index = _read_group(text, index)
                out.append(_sqrt(root, _latex_to_text(body)))
                continue
            if name in ("overline", "bar", "vec", "hat"):
                body, index = _read_group(text, index)
                mark = {"overline": "̄", "bar": "̄",
                        "vec": "⃗", "hat": "̂"}[name]
                out.append(_latex_to_text(body) + mark)
                continue
            if name == "pmod":
                body, index = _read_group(text, index)
                out.append(f"(mod {_latex_to_text(body)})")
                continue
            if name in ("begin", "end"):
                _, index = _read_group(text, index)
                continue
            if name in ("left", "right"):
                continue
            if name in _GREEK:
                out.append(_GREEK[name])
                continue
            if name in _SYMBOLS:
                out.append(_SYMBOLS[name])
                continue
            # 不认识：去掉反斜杠保留名字，至少可读。
            out.append(name)
            continue
        if char in "^_":
            body, index = _read_group(text, index + 1)
            converted = _latex_to_text(body)
            mapped = _map_script(converted, _SUP if char == "^" else _SUB)
            out.append(mapped if mapped is not None
                       else f"{char}({converted})")
            continue
        if char in "{}":
            index += 1
            continue
        if char == "&":
            out.append(", ")
            index += 1
            continue
        if char == "*":
            out.append("×")
            index += 1
            continue
        out.append(char)
        index += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()
