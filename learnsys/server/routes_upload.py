"""浏览器附件上传：图片存盘给 Agent 看，文档抽成文字随请求带上。

浏览器拿不到本机文件路径，所以前端把文件读成 base64 POST 上来：
- 图片 → 落到当天的「问答截图」目录，返回路径（知识库/复盘也能看到）；
- 文档 → 临时存盘、用 `study.extract_doc_text` 抽文字，抽完删除，返回文本。
只接受白名单后缀；单文件上限 20MB；写接口要令牌。
"""
from __future__ import annotations

import base64
import binascii
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import config as app_config
from learnsys.server.security import require_token

router = APIRouter()

MAX_BYTES = 20 * 1024 * 1024
IMAGE_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DOC_SUFFIX = {".pdf", ".docx", ".pptx", ".txt", ".md"}
MAX_DOC_CHARS = 200_000


class UploadRequest(BaseModel):
    name: str = ""
    data: str = Field(min_length=1)
    kind: str = "auto"          # auto / image / doc


def _suffix(name: str) -> str:
    match = re.search(r"(\.[A-Za-z0-9]{1,8})$", str(name or "").strip())
    return match.group(1).lower() if match else ""


def _decode(data: str) -> bytes:
    """接受 `data:image/png;base64,xxx` 或纯 base64；超限直接 413。"""
    raw = str(data or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    if len(raw) > MAX_BYTES * 4 // 3 + 1024:
        raise HTTPException(status_code=413, detail="文件超过 20MB，先压小一点再传")
    try:
        blob = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="上传内容不是有效的 base64") from exc
    if not blob:
        raise HTTPException(status_code=400, detail="上传内容为空")
    if len(blob) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 20MB，先压小一点再传")
    return blob


@router.post("/api/upload")
def upload(req: UploadRequest, _=Depends(require_token)):
    suffix = _suffix(req.name)
    wanted = str(req.kind or "auto").lower()
    if wanted == "image" and suffix not in IMAGE_SUFFIX:
        raise HTTPException(status_code=400, detail="图片只支持 png / jpg / webp / gif")
    if wanted == "doc" and suffix not in DOC_SUFFIX:
        raise HTTPException(status_code=400, detail="文档只支持 pdf / docx / pptx / txt / md")
    if suffix not in IMAGE_SUFFIX | DOC_SUFFIX:
        raise HTTPException(status_code=400,
                            detail="不支持这种文件：只收图片（png/jpg/webp/gif）和文档（pdf/docx/pptx/txt/md）")

    blob = _decode(req.data)
    stem = str(req.name or "附件")[:80]

    if suffix in IMAGE_SUFFIX:
        target_dir = Path(app_config.ask_image_dir())
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"网页_{uuid.uuid4().hex[:12]}{suffix}"
        try:
            target.write_bytes(blob)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"图片存不下来：{exc}") from exc
        return {"kind": "image", "name": stem, "path": str(target),
                "size": len(blob)}

    # 文档：临时落盘 → 抽文字 → 删除（原文还留在用户自己电脑上）
    tmp_dir = Path(app_config.DATA_ROOT) / "上传" / "临时"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{uuid.uuid4().hex[:12]}{suffix}"
    try:
        tmp.write_bytes(blob)
        from learnsys.services.study import extract_doc_text
        text = extract_doc_text(str(tmp)) or ""
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读文档失败：{exc}") from exc
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

    text = text.strip()
    if len(text) < 20:
        raise HTTPException(
            status_code=400,
            detail="这份文档几乎没读到文字（扫描版 PDF 需要先 OCR），换一份试试")
    truncated = False
    if len(text) > MAX_DOC_CHARS:
        text = text[:MAX_DOC_CHARS]
        truncated = True
    return {"kind": "doc", "name": stem, "text": text, "chars": len(text),
            "truncated": truncated}
