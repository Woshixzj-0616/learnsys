"""Agent 的模型配置。

密钥来源（按顺序）：
1. `D:/学习系统/设置.json` 里的 `agent` / `vision` 两段 —— 开源版的正式入口；
2. 环境变量 / `~/.claude/settings.json` 的 `env` —— 本机便利回退，免得同一把 key 填两处；
3. 都没有 = 未配置，界面引导去设置，不抛裸异常。

**密钥永远不进日志、不进仓库**。这里只负责读，不负责写。
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

from learnsys import config as app_config

CLAUDE_SETTINGS = pathlib.Path.home() / ".claude" / "settings.json"

DEFAULT_BASE = "https://api.deepseek.com/anthropic"
DEFAULT_MODEL = "deepseek-flash"          # DeepSeek-V4.1-Flash（2026-10-23 起默认）
DEFAULT_FAST_MODEL = "deepseek-flash"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_VISION_MODEL = "glm-4v-flash"


def _claude_env() -> dict[str, str]:
    """读 Claude Code 的本机配置（只取 env 段）。读不到就当空 —— 这是回退，不是必需。"""
    try:
        data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}
    env = data.get("env") if isinstance(data, dict) else None
    if not isinstance(env, dict):
        return {}
    return {str(k): str(v) for k, v in env.items() if v not in (None, "")}


def clean_model(value: str) -> str:
    """去掉 Claude Code 的上下文标记：`deepseek-flash[1M]` → `deepseek-flash`。

    `[1M]` 是 Claude Code 的显示/路由标记，不是 API 的模型 ID；
    原样发过去有的中转认、有的不认，统一去掉最省事。
    """
    return re.sub(r"\[[^\]]*\]\s*$", "", str(value or "").strip())


def _section(raw: dict, key: str) -> dict:
    value = raw.get(key)
    return value if isinstance(value, dict) else {}


def _vision_auth_style(base: str) -> str:
    """视觉端点用哪种鉴权：Anthropic Messages 还是 OpenAI 兼容。"""
    value = str(base or "").rstrip("/").lower()
    if value.endswith("/anthropic") or "api.anthropic.com" in value:
        return "anthropic"
    return "openai"


def _vision_settings(vision: dict, *, base: str, token: str,
                     model: str, fast: str = "") -> tuple[str, str, str, str, bool]:
    """视觉配置；没单独填 key/base 时复用主模型那套。

    2026-10-26 实测：DeepSeek 的 key 与文本接口已支持图片输入
    （`deepseek-flash` 能读出形状/颜色/箭头；`deepseek-v4-pro` 不行），
    所以同一把 key 不再需要填两处；复用主配置时优先用快模型。
    显式填了 vision 段就完全按 vision 段走，不猜。
    """
    key = str(vision.get("api_key") or "").strip()
    vbase = str(vision.get("base_url") or "").strip().rstrip("/")
    vmodel = str(vision.get("model") or DEFAULT_VISION_MODEL).strip()
    uses_agent = False
    if not key and not vbase and token:
        key, vbase, vmodel = token, base, (fast or model)
        uses_agent = True
    style = _vision_auth_style(vbase) if vbase else "openai"
    return vbase, key, vmodel, style, uses_agent


def _as_int(value, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _as_bool(value, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off", "关", "否")


def _as_prices(raw) -> dict[str, dict]:
    """`{模型: {input, output, cache_read}}`，负数/非数字当 0；空模型名丢弃。"""
    if not isinstance(raw, dict):
        return {}
    prices: dict[str, dict] = {}
    for name, value in raw.items():
        model = clean_model(str(name or ""))
        if not model or not isinstance(value, dict):
            continue
        entry = {
            "input": _as_float(value.get("input")),
            "output": _as_float(value.get("output")),
            "cache_read": _as_float(value.get("cache_read")),
        }
        if any(entry.values()):
            prices[model] = entry
    return prices


def _as_limit(value) -> float:
    """每日上限：负数当 0（不限）。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _as_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


@dataclass(frozen=True)
class AgentConfig:
    # 文本主模型（Anthropic Messages 协议）
    base_url: str
    auth_token: str
    model: str
    fast_model: str
    max_tokens: int
    thinking: bool

    # 视觉模型（OpenAI 兼容协议，可选）
    vision_base_url: str
    vision_api_key: str
    vision_model: str

    # 本地数据
    data_root: pathlib.Path
    profile_path: pathlib.Path

    # 回答速度档：fast = 轻量模型不思考；balanced = 主模型不思考；deep = 主模型思考
    speed: str = "balanced"

    # 自动路由：off / shadow（只记建议）/ on（按建议执行）
    auto_route: str = "off"
    # 自动路由需要升级时用的强模型；空 = 退回主模型（只多开思考）
    strong_model: str = ""

    # 成本估算：每 100 万 token 的单价；0 = 未配置（不猜价格）
    # 全局价是兜底；`prices` 按模型覆盖，键是模型名。
    price_input: float = 0.0
    price_output: float = 0.0
    price_cache_read: float = 0.0
    prices: dict[str, dict] = field(default_factory=dict)
    currency: str = "USD"

    # 每日上限：0 = 不限。达到后 agent.run 直接拒绝（硬拒绝，不发模型请求）。
    daily_cost_limit: float = 0.0
    daily_call_limit: int = 0

    # 任务 → 模型（可选）。为空 = 全部走现有 speed 档，行为不变。
    # 键：explain / guide / quiz / quick / translate / analyze / review
    routes: dict[str, str] = field(default_factory=dict)

    # 视觉端点鉴权：openai（GLM/Qwen 等）或 anthropic（DeepSeek / Claude）。
    vision_auth_style: str = "openai"
    # True = 视觉复用主模型的 key/base/model（用户只填了一处）。
    vision_uses_agent: bool = False

    def model_for(self, task: str, default: str = "") -> str:
        """按任务取模型；没配置就返回 default（调用方再退 fast_model / model）。"""
        value = (self.routes or {}).get(str(task or ""))
        return clean_model(value) if value else default

    @property
    def ready(self) -> bool:
        """文本问答能不能用。"""
        return bool(self.base_url and self.auth_token and self.model)

    @property
    def vision_ready(self) -> bool:
        """看图能不能用；没配就退回 OCR。"""
        return bool(self.vision_base_url and self.vision_api_key and self.vision_model)

    def public(self) -> dict:
        """给界面看的配置：**没有密钥**，只说明配没配、用的是谁。"""
        return {
            "ready": self.ready,
            "vision_ready": self.vision_ready,
            "model": self.model,
            "fast_model": self.fast_model,
            "base_url": self.base_url,
            "max_tokens": self.max_tokens,
            "speed": self.speed,
            "auto_route": self.auto_route,
            "strong_model": self.strong_model,
            "price_input": self.price_input,
            "price_output": self.price_output,
            "price_cache_read": self.price_cache_read,
            "prices": {name: dict(value) for name, value in (self.prices or {}).items()},
            "currency": self.currency,
            "daily_cost_limit": self.daily_cost_limit,
            "daily_call_limit": self.daily_call_limit,
            "routes": dict(self.routes or {}),
            "vision_model": self.vision_model if self.vision_ready else "",
        }


def load_config() -> AgentConfig:
    """读一遍当前配置。每次调用都重新读 —— 设置页保存后不用重启。"""
    user = app_config.USER if isinstance(app_config.USER, dict) else {}
    env = _claude_env()
    agent = _section(user, "agent")
    vision = _section(user, "vision")

    base = str(agent.get("base_url") or env.get("ANTHROPIC_BASE_URL")
               or DEFAULT_BASE).strip().rstrip("/")
    token = str(agent.get("auth_token") or env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    model = clean_model(
        agent.get("model")
        or env.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or env.get("ANTHROPIC_MODEL")
        or DEFAULT_MODEL
    ) or DEFAULT_MODEL
    fast = clean_model(
        agent.get("fast_model")
        or env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
        or DEFAULT_FAST_MODEL
    ) or DEFAULT_FAST_MODEL

    data_root = pathlib.Path(agent.get("data_root") or app_config.DATA_ROOT)

    # 旧配置只有 thinking 开关，没有 speed：true 视作 deep，false 视作 balanced。
    # 这样老用户的设置不会被悄悄改掉；新 UI 写 speed 后以 speed 为准。
    thinking = _as_bool(agent.get("thinking"), True)
    speed = str(agent.get("speed") or "").strip().lower()
    if speed not in ("fast", "balanced", "deep"):
        speed = "deep" if thinking else "balanced"

    auto_route = str(agent.get("auto_route") or "off").strip().lower()
    if auto_route not in ("off", "shadow", "on"):
        auto_route = "off"

    raw_routes = agent.get("routes")
    routes = {
        str(key): clean_model(str(value))
        for key, value in (raw_routes.items() if isinstance(raw_routes, dict) else [])
        if str(value or "").strip()
    }

    vision_base, vision_key, vision_model, vision_style, vision_uses_agent = (
        _vision_settings(vision, base=base, token=token, model=model, fast=fast))
    return AgentConfig(
        base_url=base,
        auth_token=token,
        model=model,
        fast_model=fast,
        max_tokens=_as_int(agent.get("max_tokens"), DEFAULT_MAX_TOKENS),
        thinking=thinking or speed == "deep",
        vision_base_url=vision_base,
        vision_api_key=vision_key,
        vision_model=vision_model,
        vision_auth_style=vision_style,
        vision_uses_agent=vision_uses_agent,
        data_root=data_root,
        profile_path=data_root / "学习档案.md",
        speed=speed,
        auto_route=auto_route,
        strong_model=clean_model(str(agent.get("strong_model") or "")),
        price_input=_as_float(agent.get("price_input")),
        price_output=_as_float(agent.get("price_output")),
        price_cache_read=_as_float(agent.get("price_cache_read")),
        prices=_as_prices(agent.get("prices")),
        currency=str(agent.get("currency") or "USD").strip()[:12] or "USD",
        daily_cost_limit=_as_limit(agent.get("daily_cost_limit")),
        daily_call_limit=int(_as_limit(agent.get("daily_call_limit"))),
        routes=routes,
    )
