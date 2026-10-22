"""工具分发器：保持中文摘要与 ok 判定，失败不静默。"""
from __future__ import annotations

from learnsys.agent import sandbox
from .context import ToolContext
from .files import run_code, write_study_file
from .materials import read_material, save_material_note, search_materials
from .records import ocr_image, read_attachment, search_records, today_summary
from .study_tools import (forget_memory, get_cet6_context, recent_wrong_items,
                          save_memory, save_wrongbook)


def execute(name: str, args: dict, ctx: ToolContext) -> tuple[str, str, bool]:
    """执行工具，返回 (给模型看的内容, 给界面看的一句话摘要, 是否成功)。

    `ok=False` 表示这次调用没拿到结果（参数错、库读失败、OCR 失败等）：
    内容仍原样回给模型换路，界面也会标红，不静默跳过。
    """
    args = args if isinstance(args, dict) else {}
    try:
        if name == "search_records":
            text = search_records(
                str(args.get("query") or ""),
                int(args.get("days") or 7),
                args.get("kinds") if isinstance(args.get("kinds"), list) else None,
                int(args.get("limit") or 8),
                data_root=ctx.data_root,
            )
            return text, "查了本地学习记录", True
        if name == "today_summary":
            text = today_summary(data_root=ctx.data_root)
            ok = not text.startswith(("读今天的记录失败", "统计今天的记录失败"))
            return text, "看了今天的学习概况", ok
        if name == "recent_wrong_items":
            return (recent_wrong_items(int(args.get("limit") or 8),
                                       int(args.get("days") or 0),
                                       int(args.get("material_id") or 0), ctx=ctx),
                    "读了最近的错题", True)
        if name == "read_attachment":
            return read_attachment(int(args.get("offset") or 0), ctx=ctx), "读了挂载文档", True
        if name == "ocr_image":
            text = ocr_image(str(args.get("path") or ""), ctx=ctx)
            ok = not text.startswith(("这个路径不在", "图片不存在", "OCR 没成功"))
            return text, "对截图做了 OCR", ok
        if name == "search_materials":
            text = search_materials(str(args.get("query") or ""),
                                    int(args.get("limit") or 5), ctx=ctx)
            ok = not text.startswith(("搜索词是空的", "搜资料库失败"))
            return text, "搜了资料库", ok
        if name == "read_material":
            text = read_material(int(args.get("material_id") or 0),
                                 int(args.get("offset") or 0),
                                 int(args.get("length") or 6000), ctx=ctx)
            ok = not text.startswith(("读资料失败", "没有 id="))
            return text, "读了资料正文", ok
        if name == "get_cet6_context":
            return (get_cet6_context(
                str(args.get("paper_id") or ""), str(args.get("section") or ""),
                str(args.get("item") or ""), int(args.get("limit") or 40), ctx=ctx),
                "读了六级精听进度", True)
        if name == "save_material_note":
            text = save_material_note(
                str(args.get("title") or ""), str(args.get("content") or ""),
                str(args.get("tags") or ""), ctx=ctx)
            if text.startswith("已保存"):
                preview, ok = "保存了资料笔记", True
            elif "已经存在" in text:
                preview, ok = "资料库里已有这份内容", True
            else:
                preview, ok = "资料笔记没有保存", False
            return text, preview, ok
        if name == "write_study_file":
            text = write_study_file(
                str(args.get("relative_path") or ""),
                str(args.get("content") or ""), ctx=ctx)
            ok = text.startswith("已保存")
            return text, ("保存了学习档案文件" if ok else "学习档案没有保存"), ok
        if name == "run_code":
            result = sandbox.run(
                str(args.get("language") or ""), str(args.get("code") or ""),
                stdin_text=str(args.get("stdin") or ""))
            return result.render(), result.preview(), result.ok
        if name == "save_memory":
            text = save_memory(str(args.get("content") or ""),
                               str(args.get("kind") or "preference"), ctx=ctx)
            return text, ("记住了这条长期偏好" if text.startswith("已记住")
                          else "长期记忆已在" if text.startswith("这条已经")
                          else "长期记忆没保存"), text.startswith(("已记住", "这条已经"))
        if name == "forget_memory":
            text = forget_memory(int(args.get("memory_id") or 0), ctx=ctx)
            return text, ("忘掉了一条长期记忆" if text.startswith("已忘掉")
                          else "没找到那条记忆"), text.startswith("已忘掉")
        if name == "save_wrongbook":
            text = save_wrongbook(
                str(args.get("question") or ""), str(args.get("my_answer") or ""),
                str(args.get("correct_answer") or ""), str(args.get("tags") or ""),
                ctx=ctx)
            if text.startswith("已收进"):
                preview = "已收进错题本"
            elif text.startswith("这道题已经"):
                preview = "错题已在错题本"
            elif "失败" in text:
                preview = "错题本保存失败"
            else:
                preview = "没有收进错题本"
            ok = text.startswith(("已收进", "这道题已经"))
            return text, preview, ok
    except Exception as exc:
        return f"工具执行失败：{exc}", "工具失败", False
    return f"没有这个工具：{name}", "未知工具", False
