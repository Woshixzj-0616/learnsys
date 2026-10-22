// 发送：把输入框 + 附件拼成请求，交给流式模块。
import { buildSnapshot } from "../../context.js";
import { state, dom } from "./state.js";
import { startStreaming } from "./stream.js";
import { addUserBlock, scrollBottom } from "./thread.js";
import { renderAttachments } from "./attachments.js";


export function sendMessage() {
  if (state.streaming) return;
  const text = dom.input.value.trim();
  if (!text && !state.image && !state.doc && !state.material) return;

  const message = text || (state.image ? "看看这张图"
    : (state.material ? "看看这份资料" : "看看这份文档"));
  const payload = {
    message,
    conversation_id: state.convId,
    mode: state.mode,
    image_path: state.image?.path || null,
    attachment_name: state.material ? "" : (state.doc?.name || ""),
    attachment_text: state.material ? "" : (state.doc?.text || ""),
    material_id: state.material?.id || null,
    surface: "ask",
    context_snapshot: state.material ? buildSnapshot({
      surface: "ask",
      object_type: "material",
      object_id: String(state.material.id),
      title: state.material.title || "",
      surrounding: {
        kind: state.material.kind || "",
        chars: state.material.chars || 0,
      },
      provenance: { page: "ask", via: "material-picker" },
    }) : null,
  };

  if (state.messages.length === 0) dom.inner.innerHTML = "";
  const shown = message
    + (state.image ? `\n［图片：${state.image.name}］` : "")
    + (state.doc ? `\n［文档：${state.doc.name}］` : "")
    + (state.material ? `\n［资料：${state.material.title}］` : "");
  addUserBlock(shown);
  state.messages.push({ role: "user", content: { text: message } });

  dom.input.value = "";
  dom.input.style.height = "auto";
  state.image = null;
  state.doc = null;
  state.material = null;
  renderAttachments();
  dom.status.textContent = "";
  scrollBottom(true);

  startStreaming(payload);
}
