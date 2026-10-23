"""六级精听的请求模型：增量同步与整卷审计共用。

单独放一个文件，避免 `routes_cet6.py` 继续变长，也避免新旧路由互相导入。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Cet6Sentence(BaseModel):
    sentence: int = 0
    en: str = ""
    tags: list[str] = Field(default_factory=list)
    note: str = ""
    loops: int = 0
    plays: int = 0


class Cet6Sync(BaseModel):
    paper: str = ""
    paper_id: str = ""
    section: str = ""
    item: str = ""
    sentences: list[Cet6Sentence] = Field(default_factory=list)
    analysis: dict | None = None
    done: list[int] | None = None   # None = 不碰完成状态；[...] = 该段完整状态


class Cet6SyncItem(BaseModel):
    section: str = ""
    item: str = ""
    sentences: list[Cet6Sentence] = Field(default_factory=list)
    done: list[int] = Field(default_factory=list)   # 该段完整完成状态；[] = 一段都没完成


class Cet6Skipped(BaseModel):
    section: str = ""
    item: str = ""
    reason: str = ""


class Cet6PaperSync(BaseModel):
    """整卷审计：一次请求同时完成比对、写入与写后校验。"""
    paper: str = ""
    paper_id: str = ""
    items: list[Cet6SyncItem] = Field(default_factory=list)
    hydration: str = "local"        # state / local / legacy / empty
    mode: str = "http"              # http / file
    paper_sig: str = ""
    client_ts: str = ""
    client_day: str = ""
    push_failed: int = 0
    skipped_items: list[Cet6Skipped] = Field(default_factory=list)
