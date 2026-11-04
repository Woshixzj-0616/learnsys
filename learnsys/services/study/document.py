"""课件 / 文档解析：PDF / DOCX / PPTX / TXT / MD → 正文 + 页数。

PDF 用换页符 `\\f` 分页、PPTX 用「--- 第 N 页 ---」分页，资料检索靠它算页码。
"""
from __future__ import annotations

import pathlib


def extract_document(path: str) -> dict:
    """课件/文档 → 正文 + 页数 + 类型。

    PDF 用换页符 `\\f` 分页、PPTX 用「--- 第 N 页 ---」分页，资料检索靠它算页码；
    DOCX/TXT/MD 没有可靠页边界，页数记 0。
    """
    p = pathlib.Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        import pymupdf
        pages = []
        with pymupdf.open(str(p)) as doc:
            for page in doc:
                pages.append(page.get_text())
        return {"kind": "pdf", "text": "\f".join(pages), "pages": len(pages)}
    if suffix == ".docx":
        import docx
        doc = docx.Document(str(p))
        text = "\n".join(par.text for par in doc.paragraphs if par.text.strip())
        return {"kind": "docx", "text": text, "pages": 0}
    if suffix == ".pptx":
        from pptx import Presentation
        prs = Presentation(str(p))
        parts = []
        for index, slide in enumerate(prs.slides, 1):
            texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    t = shape.text_frame.text.strip()
                    if t:
                        texts.append(t)
            if texts:
                parts.append(f"--- 第 {index} 页 ---\n" + "\n".join(texts))
        return {"kind": "pptx", "text": "\n\n".join(parts), "pages": len(prs.slides)}
    if suffix in (".txt", ".md"):
        return {"kind": suffix[1:],
                "text": p.read_text(encoding="utf-8", errors="replace"), "pages": 0}
    raise ValueError(f"还不支持 {suffix} 文档（先支持 PDF/DOCX/PPTX/TXT/MD）")


def extract_doc_text(path: str) -> str:
    """旧接口：只取正文（一次性附件用）。新代码优先用 `extract_document`。

    一次性附件不需要页码，把换页符换成换行，别把控制字符塞进提示词。
    """
    return extract_document(path)["text"].replace("\f", "\n")
