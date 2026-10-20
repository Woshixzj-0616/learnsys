"""设置页的后端：读掩码配置、保存设置、测试连接、立即备份。

密钥**只进不出**：GET 只告诉界面「配没配、尾号四位」；POST 留空 = 不改。
写文件是原子的（临时文件 + 替换），不会把正在用的 设置.json 写坏。
`hotkey` / `backup_dir` 仍是启动时读的常量，保存后要重启才生效 —— 接口会如实说。
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import config as app_config
from learnsys.agent.config import load_config
from learnsys.agent import vision
from learnsys.modules import load_registry
from learnsys.server.security import require_token

router = APIRouter()

_HOTKEY_RE = re.compile(r"^(?:(?:alt|ctrl|control|shift|win)\+)+([a-z]|f(?:[1-9]|1[0-9]|2[0-4]))$",
                        re.IGNORECASE)

# 1×1 透明 PNG：测视觉链路用，真发一张图才算测到「模型收不收图」
_TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
             "AAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=")


def _mask(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    return "••••" + (value[-4:] if len(value) > 4 else "****")


def _backup_dir(raw: dict) -> pathlib.Path:
    custom = raw.get("backup_dir")
    if custom:
        return pathlib.Path(str(custom))
    return app_config.DATA_ROOT.parent / "学习系统备份"


def _module_ids() -> list[str]:
    return [str(m.get("id")) for m in load_registry().get("modules", [])]


def _settings_with_template() -> dict:
    app_config.ensure_settings_file()
    data = app_config.load_settings()
    if not data:
        data = json.loads(json.dumps(app_config.SETTINGS_TEMPLATE, ensure_ascii=False))
    return data


@router.get("/api/settings")
def get_settings(_=Depends(require_token)):
    cfg = load_config()
    raw = app_config.load_settings()
    agent_raw = raw.get("agent") if isinstance(raw.get("agent"), dict) else {}
    vision_raw = raw.get("vision") if isinstance(raw.get("vision"), dict) else {}
    modules_raw = raw.get("modules") if isinstance(raw.get("modules"), dict) else {}

    token_source = ("file" if agent_raw.get("auth_token")
                    else ("env" if cfg.auth_token else "none"))
    key_source = ("file" if vision_raw.get("api_key")
                  else ("env" if cfg.vision_api_key else "none"))
    return {
        "agent": {
            "base_url": cfg.base_url,
            "model": cfg.model,
            "fast_model": cfg.fast_model,
            "max_tokens": cfg.max_tokens,
            "thinking": cfg.thinking,
            "ready": cfg.ready,
            "auth_token_set": bool(cfg.auth_token),
            "auth_token_mask": _mask(cfg.auth_token),
            "auth_token_source": token_source,
        },
        "vision": {
            "base_url": cfg.vision_base_url,
            "model": cfg.vision_model,
            "ready": cfg.vision_ready,
            "api_key_set": bool(cfg.vision_api_key),
            "api_key_mask": _mask(cfg.vision_api_key),
            "api_key_source": key_source,
        },
        "hotkey": app_config.ASK_HOTKEY,
        "data_root": str(app_config.DATA_ROOT),
        "backup_dir": str(_backup_dir(raw)),
        "settings_path": str(app_config.SETTINGS_FILE),
        "modules": {mid: bool(modules_raw.get(mid, True)) for mid in _module_ids()},
        "restart_fields": ["hotkey", "backup_dir"],
    }


class AgentPatch(BaseModel):
    base_url: str | None = None
    auth_token: str | None = None
    model: str | None = None
    fast_model: str | None = None
    max_tokens: int | None = Field(default=None, ge=64, le=131072)
    thinking: bool | None = None


class VisionPatch(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class SettingsPatch(BaseModel):
    agent: AgentPatch | None = None
    vision: VisionPatch | None = None
    hotkey: str | None = None
    modules: dict[str, bool] | None = None


def _put(data: dict, section: str, values: dict) -> None:
    if not values:
        return
    target = data.get(section)
    if not isinstance(target, dict):
        target = {}
        data[section] = target
    target.update(values)


@router.post("/api/settings")
def save_settings(patch: SettingsPatch, _=Depends(require_token)):
    data = _settings_with_template()
    changed: list[str] = []

    if patch.agent is not None:
        agent = patch.agent.model_dump(exclude_unset=True, exclude_none=True)
        # 密钥空串 = 不改（界面拿不到明文，回填不了）
        if not str(agent.get("auth_token") or "").strip():
            agent.pop("auth_token", None)
        for key in ("base_url", "model", "fast_model"):
            if key in agent:
                agent[key] = str(agent[key]).strip()
        _put(data, "agent", agent)
        changed.extend(f"agent.{k}" for k in agent)

    if patch.vision is not None:
        vision_patch = patch.vision.model_dump(exclude_unset=True, exclude_none=True)
        if not str(vision_patch.get("api_key") or "").strip():
            vision_patch.pop("api_key", None)
        for key in ("base_url", "model"):
            if key in vision_patch:
                vision_patch[key] = str(vision_patch[key]).strip()
        _put(data, "vision", vision_patch)
        changed.extend(f"vision.{k}" for k in vision_patch)

    restart: list[str] = []
    if patch.hotkey is not None:
        hotkey = str(patch.hotkey).strip().replace(" ", "")
        if hotkey and not _HOTKEY_RE.match(hotkey):
            raise HTTPException(
                status_code=400,
                detail="快捷键格式不对：写成 Alt+Q、Ctrl+Shift+F2 这样（修饰键 + 一个字母/数字/F1–F24）")
        data["hotkey"] = hotkey
        changed.append("hotkey")
        restart.append("hotkey")

    if patch.modules is not None:
        known = set(_module_ids())
        current = data.get("modules") if isinstance(data.get("modules"), dict) else {}
        current.update({k: bool(v) for k, v in patch.modules.items() if k in known})
        data["modules"] = current
        changed.append("modules")

    try:
        target = pathlib.Path(app_config.SETTINGS_FILE)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"设置没写进去：{exc}") from exc

    # load_config() 每次重读 app_config.USER；原地更新，文本/视觉模型立即生效
    app_config.USER.clear()
    app_config.USER.update(data)

    return {"ok": True, "saved": changed, "restart_required": restart,
            "message": "已保存" + ("；热键要重启问一问才生效" if restart else "")}


class TestRequest(BaseModel):
    kind: str = "text"


def _test_text(cfg) -> dict:
    if not cfg.ready:
        return {"ok": False, "message": "还没配置：地址、密钥、模型名至少缺一项"}
    from learnsys.agent import provider_anthropic
    tiny = dataclasses.replace(cfg, max_tokens=8, thinking=False)
    started = time.monotonic()
    text = ""
    try:
        for event in provider_anthropic.stream_messages(
                tiny, "只回复一个「好」字。",
                [{"role": "user", "content": [{"type": "text", "text": "回复：好"}]}],
                None, timeout=20.0):
            if event.kind == "text":
                text += event.text
            elif event.kind == "done":
                break
    except Exception as exc:
        return {"ok": False, "message": f"连不上：{exc}"}
    ms = int((time.monotonic() - started) * 1000)
    return {"ok": True, "message": f"文本模型可用（{cfg.model}，{ms} 毫秒）", "sample": text[:40]}


def _test_vision(cfg) -> dict:
    if not cfg.vision_ready:
        return {"ok": False, "message": "还没配置视觉模型：地址、密钥、模型名至少缺一项"}
    body = {
        "model": cfg.vision_model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "只回复一个「好」字。"},
            {"type": "image_url", "image_url": {"url": _TINY_PNG}},
        ]}],
        "max_tokens": 8,
    }
    request = urllib.request.Request(
        vision.chat_url(cfg.vision_base_url),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg.vision_api_key}"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200].replace("\n", " ")
        except Exception:
            pass
        return {"ok": False, "message": f"视觉服务回了 {exc.code}" + (f"：{detail}" if detail else "")}
    except Exception as exc:
        return {"ok": False, "message": f"连不上视觉服务：{exc}"}
    ms = int((time.monotonic() - started) * 1000)
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "message": f"视觉服务返回的不是 JSON：{raw[:120]}"}
    return {"ok": True, "message": f"视觉模型可用（{cfg.vision_model}，{ms} 毫秒）"}


@router.post("/api/settings/test")
def test_settings(req: TestRequest, _=Depends(require_token)):
    cfg = load_config()
    if req.kind == "vision":
        return _test_vision(cfg)
    return _test_text(cfg)


@router.post("/api/settings/backup")
def backup_now(_=Depends(require_token)):
    from learnsys.ask import backup
    raw = app_config.load_settings()
    try:
        path = backup.do_backup(app_config.DATA_ROOT, _backup_dir(raw))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"备份失败：{exc}") from exc
    size = path.stat().st_size / 1024 / 1024 if path.exists() else 0
    return {"ok": True, "path": str(path), "size_mb": round(size, 1),
            "message": f"备份完成：{path.name}（{size:.1f} MB）"}
