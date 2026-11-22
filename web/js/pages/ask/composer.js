// 发送：把输入框 + 附件拼成请求，交给流式模块。
import { buildSnapshot } from "../../context.js";
import { toast } from "../../ui.js";
import { state, dom } from "./state.js";
import { startStreaming } from "./stream.js";
import { addUserBlock, scrollBottom } from "./thread.js";
import { renderAttachments } from "./attachments.js";


function lastUserText() {
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const item = state.messages[index];
    if (item?.role !== "user") continue;
    const text = String(item.content?.text || "").trim();
    if (text) return text;
  }
  return "";
}


/** 对上一题再跑一轮：deep=True 让后端开思考档。 */
export function sendDeep() {
  if (state.streaming) {
    toast("先等这一轮写完再做深入讲");
    return;
  }
  const text = dom.input.value.trim() || lastUserText();
  if (!text) {
    toast("先把要深入讲的问题写在输入框里");
    dom.input.focus();
    return;
  }
  sendMessage({ deep: true, text });
}


export function sendMessage(options = {}) {
  if (state.streaming) return;
  const typed = dom.input.value.trim();
  const text = String(options.text ?? typed).trim();
  if (!text && !state.image && !state.doc && !state.material && !state.recording) return;

  const message = text || (state.image ? "看看这张图"
    : (state.recording ? "看看这段录像"
      : (state.material ? "看看这份资料" : "看看这份文档")));
  const payload = {
    message,
    conversation_id: state.convId,
    mode: state.mode,
    image_path: state.image?.path || null,
    attachment_name: state.material ? "" : (state.doc?.name || ""),
    attachment_text: state.material ? "" : (state.doc?.text || ""),
    material_id: state.material?.id || null,
    recording_id: state.recording?.id || null,
    surface: "ask",
    deep: !!options.deep,
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
  const shown = (options.deep ? "［深入讲］" : "") + message
    + (state.image ? `\n［图片：${state.image.name}］` : "")
    + (state.doc ? `\n［文档：${state.doc.name}］` : "")
    + (state.material ? `\n［资料：${state.material.title}］` : "");
  addUserBlock(shown);
  state.messages.push({ role: "user", content: { text: message } });

  dom.input.value = "";
  dom.input.style.height = "auto";
  state.image = null;
  state.doc = null;
  if (!state.materialPinned) state.material = null;   // 固定后连续几轮都带同一份资料
  renderAttachments();
  dom.status.textContent = "";
  scrollBottom(true);

  startStreaming(payload);
}
