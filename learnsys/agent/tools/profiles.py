"""工具 profile 解析：把 profile 里的工具名映射成 schema 对象。

`schemas.py` 只保留 schema 定义；本文件放「按入口/模式给哪些工具」的唯一判定，
避免 schemas.py 继续贴着 500 行红线增长。

旧入口（surface=ask/cet6/video/quickbar）的行为保持不变；只有显式传
`profile="assistant"` / `"assistant.quick"` 时才走新的问答白名单。
"""
from __future__ import annotations

from learnsys.agent.qa import profile as qa_profile


def _schema_index(module) -> dict[str, dict]:
    """从 schemas 模块里收集所有带 name 的 schema（含列表里的）。"""
    index: dict[str, dict] = {}
    for value in vars(module).values():
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            index[value["name"]] = value
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    index[item["name"]] = item
    return index


def schemas_for(mode: str = "explain", *, use_tools: bool = True,
                surface: str = "ask", profile: str = "", message: str = "",
                has_image: bool = False, has_attachment: bool = False):
    """按 profile / 入口 / 模式给工具清单。

    - profile=assistant：9 个核心 + 2 个记忆 + 按意图追加；工作/生活/系统工具不出现；
    - profile=assistant.quick：快捷栏轻量白名单（8–9 个）；
    - surface=cet6 不再有专属工具，按 assistant 白名单处理；
    - profile 为空：保持旧 surface 逻辑，兼容录像 / 工作台。
    """
    if not use_tools:
        return None
    from . import schemas as s

    surface = str(surface or "ask").lower()
    if not profile and surface == "cet6":
        profile = "assistant"
    if profile:
        names = qa_profile.tool_names(
            profile, mode=mode, message=message,
            has_image=has_image, has_attachment=has_attachment)
        if names is not None:
            index = _schema_index(s)
            return [index[name] for name in names if name in index]

    # —— 以下为旧入口逻辑，保持行为不变（CET6 已在上面转到 assistant）——
    memory = [s.SAVE_MEMORY_SCHEMA, s.FORGET_MEMORY_SCHEMA]
    if mode == "quick":
        return list(memory)

    learning = [s.MAKE_PLAN_SCHEMA, s.RECENT_WRONG_ITEMS_SCHEMA]
    core = learning + list(s.TOOL_SCHEMAS)
    if surface == "video":
        return core + memory + [s.SAVE_MATERIAL_NOTE_SCHEMA, s.ADD_VOCAB_SCHEMA]
    if surface == "quickbar":
        return core + memory + list(s.WEB_SCHEMAS) + [s.ADD_VOCAB_SCHEMA]

    schemas = list(core) + list(memory)
    if mode != "quiz":
        schemas += (s.WEB_SCHEMAS
                    + [s.OPEN_FILE_SCHEMA, s.LAUNCH_APP_SCHEMA,
                       s.OPEN_URL_SCHEMA, s.BROWSER_STATUS_SCHEMA,
                       s.BROWSER_HISTORY_SCHEMA,
                       s.SEARCH_LOCAL_FILES_SCHEMA, s.READ_LOCAL_FILE_SCHEMA])
        schemas += s.WRITING_WRITE_SCHEMAS
        schemas += [s.LIFE_CARDS_SCHEMA, s.LIFE_ITEMS_SCHEMA, s.ART_WORKS_SCHEMA]
    schemas += [s.SAVE_MATERIAL_NOTE_SCHEMA, s.WRITE_STUDY_FILE_SCHEMA,
                s.RUN_CODE_SCHEMA]
    schemas.append(s.SAVE_WRONGBOOK_SCHEMA)
    return schemas
