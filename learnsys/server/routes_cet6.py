"""六级精听：静态挂载 `/cet6/` + AI 分析任务 + 翻译 + 断点同步 + 旧接口兼容。"""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from learnsys import agent, config, store   # agent 保留：旧测试按 routes_cet6.agent.run 打桩
from learnsys.server.cet6_models import Cet6Sentence, Cet6Sync
from learnsys.server.security import require_token
from learnsys.services import analysis, observability, results, translate

router = APIRouter()

ENTRY = "/cet6/工作台/精听工作台.html"


def _missing_page() -> HTMLResponse:
    """模块没装时给一张能读懂的中文说明（iframe 里直接显示 JSON 太难看）。"""
    return HTMLResponse("""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>六级精听 · 未安装</title>
<style>body{background:#1b1e23;color:#dfe6ee;font-family:'Microsoft YaHei UI',sans-serif;
padding:40px;line-height:1.8}code{color:#f5b74e}a{color:#6ea8ff}</style>
<h2>还没装六级精听模块</h2>
<p>把「六级精听」目录放到学习工作台旁边，或在 <code>设置.json</code> 里填 <code>cet6_dir</code>，
然后重启学习工作台。</p>
<p>目录里需要有 <code>工作台\\精听工作台.html</code> 和 <code>试卷\\</code>。</p>
</html>""", status_code=404)


@router.get("/cet6", include_in_schema=False)
@router.get("/cet6/", include_in_schema=False)
def cet6_root():
    """`/cet6` 直接进工作台；模块没装时给一句中文说明，别回一个空白 404。"""
    if not config.cet6_workbench().exists():
        return _missing_page()
    return RedirectResponse(urllib.parse.quote(ENTRY, safe="/"), status_code=307)


@router.get("/cet6/工作台/精听工作台.html", include_in_schema=False)
def cet6_workbench_file():
    """只放行工作台这一个 HTML（自包含），同目录的 .bat 不暴露。"""
    path = config.cet6_workbench()
    if not path.exists():
        return _missing_page()
    return FileResponse(path, media_type="text/html; charset=utf-8")


def mount_static(app: FastAPI) -> bool:
    """把六级试卷挂到 `/cet6/试卷/`（工作台用相对路径 `../试卷/` 找音频，路径不能变）。

    只挂试卷：根目录的脚本、原始音频、工作台目录里的批处理都不进浏览器。
    """
    root = config.cet6_dir()
    papers = root / "试卷"
    if not (root / "工作台" / "精听工作台.html").exists():
        return False
    if papers.exists():
        app.mount("/cet6/试卷", StaticFiles(directory=str(papers), html=True), name="cet6-papers")
    return True


class AnalyzeRequest(BaseModel):
    """旧 `/analyze` 的形状；file:// 工作台仍在用。"""
    paper: str = ""
    paper_id: str = ""
    section: str = ""
    item: str = ""
    scope: str = "item"
    sentences: list[dict] = Field(default_factory=list)


class Cet6Import(BaseModel):
    items: dict[str, str] = Field(default_factory=dict)


class AnalysisIn(BaseModel):
    paper_id: str = ""
    paper: str = ""
    section: str = ""
    item: str = ""
    scope: str = "item"
    sentences: list[Cet6Sentence] = Field(default_factory=list)
    context: dict | None = None
    force: bool = False


class TranslateIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    kind: str = "word"
    context: dict | None = None


class TranslateItemIn(BaseModel):
    paper_id: str = ""
    section: str = ""
    item: str = ""
    sentences: list[dict] = Field(default_factory=list)


@router.post("/analyze")
def analyze_compat(req: AnalyzeRequest):
    """旧工作台硬编码的地址：保持返回形状不变，内部与任务队列共用一套提示词。"""
    try:
        return analysis.analyze_sync(req.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/cet6/analyze")
def analyze_v2(req: AnalyzeRequest):
    return analyze_compat(req)


@router.post("/api/cet6/analysis", status_code=202)
def submit_analysis(req: AnalysisIn, _=Depends(require_token)):
    try:
        return analysis.submit(req.model_dump(), force=req.force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提交分析失败：{exc}") from exc


@router.get("/api/cet6/analysis")
def latest_analysis(paper_id: str = "", section: str = "", item: str = "",
                    scope: str = "item", _=Depends(require_token)):
    if scope not in ("item", "paper"):
        scope = "item"
    tid = analysis.target_id(paper_id, section, item, scope)
    conn = store.connect()
    try:
        row = results.latest(conn, kind=analysis.ANALYSIS_KIND,
                             target_type="paper" if scope == "paper" else "item",
                             target_id=tid, scope=scope)
        if not row:
            return {"id": 0, "status": "none", "content": None}
        return results.to_public(row)
    finally:
        conn.close()


@router.get("/api/cet6/analysis/{result_id}")
def get_analysis(result_id: int, _=Depends(require_token)):
    conn = store.connect()
    try:
        row = results.get(conn, result_id)
        if not row:
            raise HTTPException(status_code=404, detail="分析结果不存在")
        return results.to_public(row)
    finally:
        conn.close()


@router.post("/api/cet6/analysis/{result_id}/cancel")
def cancel_analysis(result_id: int, _=Depends(require_token)):
    return {"ok": analysis.cancel(result_id), "id": result_id}


@router.post("/api/cet6/translate")
def translate_text(req: TranslateIn, _=Depends(require_token)):
    return translate.translate(req.text, kind=req.kind, context=req.context)


@router.post("/api/cet6/translate-item")
def translate_item(req: TranslateItemIn, _=Depends(require_token)):
    return translate.translate_sentences(
        req.sentences, paper_id=req.paper_id, section=req.section, item=req.item)


@router.get("/api/runs")
def runs(limit: int = 50, _=Depends(require_token)):
    conn = store.connect()
    try:
        return {"items": observability.recent_runs(conn, limit=limit)}
    finally:
        conn.close()


@router.post("/api/cet6/sync")
def cet6_sync(req: Cet6Sync):
    """工作台把逐句进度与分析结果送进学习工作台；失败不影响工作台。"""
    paper_id = req.paper_id or req.paper
    if not paper_id or not req.section or not req.item:
        raise HTTPException(status_code=400, detail="缺少试卷 / Section / 题型")
    conn = store.connect()
    try:
        stamp = store.now()
        store.upsert_cet6_progress(
            conn, paper_id=paper_id, paper_title=req.paper,
            section=req.section, item=req.item,
            rows=[item.model_dump() for item in req.sentences], done=req.done)
        count = store.add_breakpoint_events(
            conn, stamp=stamp, paper_id=paper_id, paper=req.paper,
            section=req.section, item=req.item,
            sentences=[item.model_dump() for item in req.sentences],
            analysis=req.analysis)
        return {"ok": True, "count": count}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/api/cet6/import")
def cet6_import(req: Cet6Import):
    """file:// 版工作台把 localStorage 快照送过来（P4 迁移桥用）。"""
    conn = store.connect()
    try:
        count = store.save_import_items(conn, req.items, store.now())
        return {"ok": True, "count": count}
    finally:
        conn.close()


@router.get("/api/cet6/import")
def cet6_restore():
    """HTTP 首开且 localStorage 为空时，把旧进度读回去（迁移桥另一端）。"""
    conn = store.connect()
    try:
        items = store.load_import_items(conn)
        return {"ok": True, "items": items, "count": len(items)}
    finally:
        conn.close()


# P17.1：整卷审计 + 服务端状态读取；单独一个路由文件，避免这里继续变长。
from .routes_cet6_sync import router as _sync_router   # noqa: E402

router.include_router(_sync_router)
