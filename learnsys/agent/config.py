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
from dataclasses import dataclass

from learnsys import config as app_config

CLAUDE_SETTINGS = pathlib.Path.home() / ".claude" / "settings.json"

DEFAULT_BASE = "https://api.deepseek.com/anthropic"
DEFAULT_MODEL = "deepseek-v4-pro"
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

    return AgentConfig(
        base_url=base,
        auth_token=token,
        model=model,
        fast_model=fast,
        max_tokens=_as_int(agent.get("max_tokens"), DEFAULT_MAX_TOKENS),
        thinking=thinking or speed == "deep",
        vision_base_url=str(vision.get("base_url") or "").strip().rstrip("/"),
        vision_api_key=str(vision.get("api_key") or "").strip(),
        vision_model=str(vision.get("model") or DEFAULT_VISION_MODEL).strip(),
        data_root=data_root,
        profile_path=data_root / "学习档案.md",
        speed=speed,
    )
