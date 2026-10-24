"""学习工作台 MCP 只读服务（stdio）。

外部客户端（Claude Code / Codex）启动本进程，用 5 个工具读取学习数据：
上下文、资料检索、读资料、到期复习、翻译。

设计约束：
- 不自己连数据库、不复制业务逻辑，全部走本机 HTTP `127.0.0.1:8765`。
- 只有 `translate` 会写翻译缓存与流水，不写问答 / 错题 / 进度。
- stdout 只放 JSON-RPC；诊断信息写 stderr。

运行：`python -m learnsys.mcp_server`（可用 `LEARNSYS_MCP_URL` 改地址）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from learnsys import product

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_URL = os.environ.get("LEARNSYS_MCP_URL", "http://127.0.0.1:8765").rstrip("/")


class BackendError(RuntimeError):
    """后台不可用或返回错误；转成工具级错误，不撕断协议。"""


class ParamError(ValueError):
    """工具参数不合法。"""


class Client:
    def __init__(self, base_url: str = DEFAULT_URL):
        self.base_url = base_url.rstrip("/")
        self.token = ""

    def _health(self) -> dict:
        try:
            with urllib.request.urlopen(self.base_url + "/api/health", timeout=10) as res:
                return json.loads(res.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise BackendError(
                "后台没有响应。先双击「学习工作台.cmd」启动，再试一次。") from exc

    def _ensure_token(self) -> str:
        if not self.token:
            self.token = str(self._health().get("token") or "")
        return self.token

    def _request(self, method: str, path: str, body: dict | None = None,
                 retry: bool = True) -> dict:
        data = None if body is None else json.dumps(
            body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json",
                     "X-Learnsys-Token": self._ensure_token()})
        try:
            with urllib.request.urlopen(request, timeout=60) as res:
                raw = res.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and retry:
                self.token = ""
                return self._request(method, path, body, retry=False)
            detail = ""
            try:
                detail = str(json.loads(exc.read().decode("utf-8")).get("detail") or "")
            except (ValueError, OSError):
                pass
            raise BackendError(detail or f"后台返回 HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise BackendError("连不上后台，确认学习工作台正在运行。") from exc
        except json.JSONDecodeError as exc:
            raise BackendError("后台返回的不是 JSON。") from exc

    def get_json(self, path: str) -> dict:
        return self._request("GET", path)

    def post_json(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

STATE_NAMES = {"new": "新卡", "learning": "学习中", "review": "复习中"}


def _tool_study_context(client: Client, args: dict) -> str:
    overview = client.get_json("/api/overview")
    today = client.get_json("/api/today")
    stats = client.get_json("/api/review/stats")
    day = today.get("date") or ""
    current = overview.get("today") or {}
    xp = current.get("xp", 0)
    goal = current.get("goal", 100)
    percent = current.get("percent", 0)
    streak = overview.get("streak", 0)
    lines = [f"今日 {day}：学习点 {xp} / {goal}（{percent}%），连续 {streak} 天"]
    transcript = today.get("transcripts") or {}
    focus = today.get("focus") or {}
    lines.append(
        f"问答 {today.get('ask_count', 0)} 条 · "
        f"转写 {transcript.get('count', 0)} 段 / {transcript.get('chars', 0)} 字 · "
        f"专注 {focus.get('minutes', 0)} 分钟（切换 {focus.get('switches', 0)} 次）")
    lines.append(
        f"待复习 {stats.get('due', 0)} 条（新卡 {stats.get('new', 0)}，"
        f"共 {stats.get('total', 0)}），今天已复习 {stats.get('reviewed_today', 0)} 条"
        + (f"；下张到期 {stats['next_due']}" if stats.get("next_due") else ""))
    cet6 = today.get("cet6") or []
    if cet6:
        parts = [f"{row.get('paper', '')} / {row.get('section', '')} / "
                 f"{row.get('item', '')}（{row.get('count', 0)} 处）"
                 for row in cet6[:5]]
        lines.append("六级断点：" + "；".join(parts))
    else:
        lines.append("六级断点：今天没有")
    return "\n".join(lines)


def _tool_search_materials(client: Client, args: dict) -> str:
    query = str(args.get("query") or "").strip()
    limit = int(args.get("limit") or 5)
    path = "/api/materials?" + urllib.parse.urlencode({"q": query, "limit": limit})
    data = client.get_json(path)
    items = data.get("items") or []
    if not items:
        return f"资料库里没有匹配「{query}」的内容。"
    lines = [f"资料库「{query}」命中 {len(items)} 份："]
    for index, item in enumerate(items, 1):
        page = f"第 {item['page']} 页" if item.get("page") else ""
        snippet = str(item.get("snippet") or "").strip().replace("\n", " ")
        lines.append(f"{index}. {item.get('title', '')}（{item.get('kind', '')}）{page}")
        if snippet:
            lines.append(f"   {snippet[:200]}")
    return "\n".join(lines)


def _tool_read_material(client: Client, args: dict) -> str:
    try:
        material_id = int(args.get("material_id"))
    except (TypeError, ValueError):
        raise ParamError("material_id 必须是整数")
    offset = max(0, int(args.get("offset") or 0))
    limit = max(1, min(int(args.get("limit") or 4000), 20000))
    data = client.get_json(f"/api/materials/{material_id}?body=1")
    item = data.get("item") or {}
    body = str(item.get("body") or "")
    if not body:
        return f"《{item.get('title', '')}》还没有正文（可能是扫描版，需要先 OCR）。"
    total = len(body)
    start = min(offset, total)
    end = min(total, start + limit)
    head = f"《{item.get('title', '')}》（共 {total} 字，第 {start + 1}–{end} 字）"
    tail = ""
    if end < total:
        tail = f"\n…（后面还有 {total - end} 字，用 offset={end} 继续）"
    return f"{head}\n{body[start:end]}{tail}"


def _tool_due_reviews(client: Client, args: dict) -> str:
    limit = max(1, min(int(args.get("limit") or 20), 100))
    data = client.get_json(f"/api/review/queue?limit={limit}")
    items = data.get("items") or []
    if not items:
        return "今天没有到期的复习卡。"
    lines = [f"到期 {len(items)} 张："]
    for index, item in enumerate(items, 1):
        title = item.get("question") if item.get("item_type") == "wrong" else item.get("word")
        kind = "错题" if item.get("item_type") == "wrong" else "生词"
        state = STATE_NAMES.get(str(item.get("state") or ""), item.get("state") or "")
        lines.append(
            f"{index}. [{kind}] {title or '（无标题）'}"
            f"（到期 {item.get('due', '')}，{state}，复习 {item.get('reps', 0)} 次）")
    return "\n".join(lines)


def _tool_translate(client: Client, args: dict) -> str:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ParamError("缺少参数：text")
    kind = str(args.get("kind") or "word")
    if kind not in ("word", "sentence", "paragraph"):
        raise ParamError("kind 只能是 word / sentence / paragraph")
    data = client.post_json("/api/services/translate", {"text": text, "kind": kind})
    if data.get("error"):
        raise BackendError(str(data.get("error")))
    parts = [f"{text} → {data.get('translation', '')}"]
    if data.get("phonetic"):
        parts[0] += f" {data['phonetic']}"
    if data.get("meaning"):
        parts.append(str(data["meaning"]))
    return "\n".join(parts)


TOOLS = {
    "study_context": {
        "description": "读取今天的学习上下文：学习点、连续天数、问答/转写/专注、"
                       "待复习与到期日、六级断点。只读。",
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
        "handler": _tool_study_context,
        "read_only": True,
    },
    "search_materials": {
        "description": "在资料库里检索（整句/关键词），返回标题、页码与片段。只读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50,
                          "default": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "handler": _tool_search_materials,
        "read_only": True,
    },
    "read_material": {
        "description": "按 id 读资料正文的一段（默认前 4000 字，可分页）。只读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "material_id": {"type": "integer", "description": "资料 id"},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20000,
                          "default": 4000},
            },
            "required": ["material_id"],
            "additionalProperties": False,
        },
        "handler": _tool_read_material,
        "read_only": True,
    },
    "due_reviews": {
        "description": "列出今天到期的错题/生词（FSRS 排期）。只读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                          "default": 20},
            },
            "additionalProperties": False,
        },
        "handler": _tool_due_reviews,
        "read_only": True,
    },
    "translate": {
        "description": "翻译单词/句子/整段。会写翻译缓存，不改学习数据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要翻译的文本"},
                "kind": {"type": "string",
                         "enum": ["word", "sentence", "paragraph"],
                         "default": "word"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        "handler": _tool_translate,
        "read_only": False,
    },
}


def _validate(schema: dict, args: dict) -> dict:
    if not isinstance(args, dict):
        raise ParamError("参数必须是对象")
    properties = schema.get("properties") or {}
    for key in args:
        if key not in properties:
            raise ParamError("不支持的参数：" + key)
    cleaned = {}
    for key in schema.get("required", []):
        if args.get(key) in (None, ""):
            raise ParamError("缺少参数：" + key)
    for key, spec in properties.items():
        value = args.get(key, spec.get("default"))
        if value is None:
            continue
        if spec.get("type") == "integer":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ParamError(f"{key} 必须是整数")
        if spec.get("enum") and value not in spec["enum"]:
            raise ParamError(f"{key} 只能是 " + " / ".join(spec["enum"]))
        cleaned[key] = value
    return cleaned


def _tool_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


_DEFAULT_CLIENT: Client | None = None


def _default_client() -> Client:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = Client()
    return _DEFAULT_CLIENT


def handle(message: dict, client: Client | None = None):
    """处理一条 JSON-RPC 消息；通知返回 None。"""
    if not isinstance(message, dict):
        return _error(None, -32600, "无效请求")
    method = str(message.get("method") or "")
    request_id = message.get("id")
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "learnsys", "version": product.VERSION,
                           "title": product.PRODUCT_NAME},
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "tools": [{
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
                "annotations": {"readOnlyHint": spec["read_only"]},
            } for name, spec in TOOLS.items()],
        }}
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        spec = TOOLS.get(name)
        if spec is None:
            return _error(request_id, -32602, f"没有这个工具：{name}")
        try:
            args = _validate(spec["inputSchema"], params.get("arguments") or {})
        except ParamError as exc:
            return _error(request_id, -32602, str(exc))
        backend = client or _default_client()
        try:
            text = spec["handler"](backend, args)
        except ParamError as exc:
            return _error(request_id, -32602, str(exc))
        except BackendError as exc:
            return {"jsonrpc": "2.0", "id": request_id,
                    "result": _tool_result(str(exc), is_error=True)}
        except Exception as exc:                     # 不把栈甩给客户端
            return {"jsonrpc": "2.0", "id": request_id,
                    "result": _tool_result(f"工具执行失败：{exc}", is_error=True)}
        return {"jsonrpc": "2.0", "id": request_id,
                "result": _tool_result(text)}
    return _error(request_id, -32601, f"不支持的方法：{method}")


def handle_line(line: str, client: Client | None = None) -> str | None:
    line = (line or "").strip()
    if not line:
        return None
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return json.dumps(_error(None, -32700, "JSON 解析失败"),
                          ensure_ascii=False)
    response = handle(message, client)
    return None if response is None else json.dumps(response, ensure_ascii=False)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print("学习工作台 MCP 只读服务已启动", file=sys.stderr)
    for line in sys.stdin:
        output = handle_line(line)
        if output:
            print(output, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
