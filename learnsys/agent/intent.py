"""判断这一轮是不是「排错 / 配置」问题。

**唯一判据**：路由（提档）、提示词（先取证）、收尾（断言审核）都从这里取，
别在 `prompts.py` / `turn.py` 里复制第二份关键词表。

规则故意保守（纯概念题必须返回 ops=False）：
- `config`：配置信号 ≥2，或 1 个配置信号 + 辅助词；配置 + 命令各 1 个也算；
- `shell`：命令信号 ≥2，或 1 个 + 辅助词；
- `traceback`：命中任意一条即算；
- `version`：版本词 + 具体技术名；
- 端口追问：「80 和 8080 都是 nginx 的」这类会话 85 的原话也能识别。

只做规则判断，不调模型、不读库。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class OpsIntent:
    ops: bool
    kind: str            # config / shell / traceback / version / none
    signals: tuple[str, ...]
    confidence: float    # 0..1，规则置信度
    needs_evidence: bool # 是否需要外部取证


# 中文紧贴英文时 `\b` 不生效（CJK 也算 \w），一律用 ASCII 边界。
_LEFT = r"(?<![A-Za-z0-9_])"
_RIGHT = r"(?![A-Za-z0-9_])"

# (可读信号名, 正则)。信号名会写进 route trace 的 reason，方便核对。
CONFIG_SIGNALS = (
    ("server 块", _LEFT + r"server\s*\{"),
    ("listen", _LEFT + r"listen\s+\d+"),
    ("server_name", _LEFT + r"server_name" + _RIGHT),
    ("root", _LEFT + r"root\s+/"),
    ("location", _LEFT + r"location\s+/"),
    ("proxy_pass", _LEFT + r"proxy_pass" + _RIGHT),
    ("include /etc", _LEFT + r"include\s+/etc/"),
    ("upstream", _LEFT + r"upstream" + _RIGHT),
    ("sites-enabled", r"sites-enabled"),
    ("nginx.conf", _LEFT + r"nginx\.conf" + _RIGHT),
    ("/etc 路径", r"/etc/[a-z0-9_.\-/]+"),
    ("端口对比", r"(?<!\d)\d{2,5}\s*(?:和|与|、)\s*\d{2,5}(?!\d)"),
)

SHELL_SIGNALS = (
    ("nginx -t", _LEFT + r"nginx\s+-[tTq]"),
    ("systemctl", _LEFT + r"systemctl" + _RIGHT),
    ("journalctl", _LEFT + r"journalctl" + _RIGHT),
    ("docker", _LEFT + r"docker" + _RIGHT),
    ("Address already in use", r"address\s+already\s+in\s+use"),
    ("Permission denied", r"permission\s+denied"),
    ("command not found", r"command\s+not\s+found"),
    ("Connection refused", r"connection\s+refused"),
    ("unknown directive", r"unknown\s+directive"),
    ("E 错误码", _LEFT + r"E\d{3}" + _RIGHT),
    ("端口占用", r"端口[^。！？\n]{0,10}(?:被)?占用|占用[^。！？\n]{0,10}端口"),
    ("命令行", _LEFT + r"(?:ls|cat|tail|head|grep|ps|ss|netstat|lsof|df|du|chmod|"
             r"chown|kill|curl|wget|apt|pip|npm)\s+-\w"),
)

TRACEBACK_SIGNALS = (
    ("Traceback", r"traceback\s+\(most recent call last\)"),
    ("文件行号", r'file\s+".*?",\s*line\s+\d+'),
    ("异常类型", _LEFT + r"(?:SyntaxError|TypeError|ValueError|KeyError|ImportError|"
             r"IndexError|AttributeError|ZeroDivisionError|NameError|"
             r"RuntimeError|OSError)" + _RIGHT),
    ("崩溃", r"(segmentation fault|core dumped)"),
)

# 辅助词：和某一个信号同时出现时，把「像在问配置」提升为排错题。
AUX_WORDS = (
    "报错", "排错", "配置", "端口", "启动失败", "不生效", "没变化", "没生效",
    "失败", "404", "502", "503",
)

VERSION_WORDS_ZH = ("版本", "最新", "弃用", "兼容", "向后兼容", "参数")
VERSION_WORD_EN_RE = re.compile(_LEFT + r"(?:deprecated|api)" + _RIGHT, re.I)
TECH_RE = re.compile(
    _LEFT + r"(?:nginx|python|docker|deepseek|linux|ubuntu|mysql|redis|java|node|"
    r"nodejs|git|golang|rust|kubernetes|k8s)" + _RIGHT, re.I)

# 「默认端口 / 被占用 / 监听」：没有别的信号也能说明是在问运行环境。
PORT_CONTEXT_RE = re.compile(r"端口[^。！？\n]{0,8}(?:默认|占用|监听)|"
                             r"(?:默认|占用|监听)[^。！？\n]{0,8}端口")
# 端口号：排除 IP 里的数字段（前后是点或数字都不算）。
PORT_NUM_RE = re.compile(r"(?<![\d.])(\d{2,5})(?![\d.])")
WEB_WORDS = ("nginx", "server", "html", "浏览器", "页面", "端口")


def _hits(text: str, table) -> list[str]:
    return [label for label, pattern in table if re.search(pattern, text, re.I)]


def _unique(items) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in items if item))


def detect_ops(message: str, context: str = "",
               attachment_text: str = "") -> OpsIntent:
    """返回这一轮的排错意图；空白输入直接返回 none。"""
    text = "\n".join(str(part or "") for part in
                     (message, context, attachment_text) if str(part or "").strip())
    if not text.strip():
        return OpsIntent(False, "none", (), 0.0, False)

    traceback = _hits(text, TRACEBACK_SIGNALS)
    config = _hits(text, CONFIG_SIGNALS)
    shell = _hits(text, SHELL_SIGNALS)
    aux = [word for word in AUX_WORDS if word in text]
    tech = [match.group(0) for match in TECH_RE.finditer(text)]

    # 任何一条 Traceback 都直接算：这是最确定的「有真实报错」。
    if traceback:
        return OpsIntent(True, "traceback", _unique(traceback)[:3], 0.9, True)

    if config and (len(config) >= 2 or aux):
        confidence = 0.8 if len(config) >= 2 else 0.6
        return OpsIntent(True, "config", _unique(config)[:3], confidence, True)

    if shell and (len(shell) >= 2 or aux):
        confidence = 0.8 if len(shell) >= 2 else 0.6
        return OpsIntent(True, "shell", _unique(shell)[:3], confidence, True)

    # 配置 + 命令各一个（例如「运行 ls -la /etc/nginx」）也够。
    if config and shell:
        return OpsIntent(True, "config", _unique(config + shell)[:3], 0.7, True)

    version_words = [word for word in VERSION_WORDS_ZH if word in text]
    version_words += VERSION_WORD_EN_RE.findall(text)
    if tech and version_words:
        return OpsIntent(True, "version", _unique(version_words + tech)[:3], 0.6, True)

    # 会话 85 的追问原话：「80 和 8080 都是 nginx 的」——端口对比 + 技术名。
    if tech and "端口对比" in config:
        return OpsIntent(True, "config", ("端口对比",), 0.55, True)

    # 「默认端口是多少」：没有技术名也按运行环境问题处理。
    if PORT_CONTEXT_RE.search(text):
        kind = "shell" if "占用" in text else "config"
        return OpsIntent(True, kind, ("端口",), 0.55, True)

    # 会话 85 的原话：多个端口 + server/html/浏览器 —— 在问 Web 服务配置。
    ports = sorted({int(match.group(1)) for match in PORT_NUM_RE.finditer(text)
                    if 1 <= int(match.group(1)) <= 65535})
    web_hint = any(word in text.lower() for word in WEB_WORDS)
    if ports and web_hint and (tech or len(ports) >= 2
                               or any(word in text for word in ("浏览器", "页面"))):
        signals = ("端口", "/".join(str(port) for port in ports[:3]))
        return OpsIntent(True, "config", signals, 0.55, True)

    return OpsIntent(False, "none", (), 0.0, False)
