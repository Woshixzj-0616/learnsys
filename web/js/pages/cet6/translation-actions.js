// 翻译页的动作：术语卡、错题卡、二稿、重批、外部校准分。
import { api } from "../../api.js";
import { toast } from "../../ui.js";

export async function addTerm(button) {
  const zh = button.dataset.zh || "";
  const en = button.dataset.en || "";
  if (!zh || !en) return;
  try {
    const data = await api.post("/api/vocab", {
      word: zh, meaning: en, context: button.dataset.note || "",
      source: "translation",
    });
    toast(data.created ? "已加入生词本" : "术语已在生词本里", "ok");
  } catch (error) {
    toast(error.message || "加入失败", "err");
  }
}

export async function addCard(current, index) {
  const error = current?.review?.errors?.[index];
  if (!error) return;
  try {
    const data = await api.post("/api/wrongbook", {
      source: "translation",
      question: `改译：${error.quote || ""}`,
      answer: error.fix || "",
      my_answer: error.quote || "",
      tags: error.type || "",
      note: error.why || "",
    });
    toast(data.created ? "已加入错题本" : "这条已经在错题本里", "ok");
  } catch (error_) {
    toast(error_.message || "加入失败", "err");
  }
}

export async function startRewrite({ current, renderEditor, invalidate, id }) {
  try {
    const parent = current?.id === id ? current
      : await api.get(`/api/cet6/train/submissions/${id}`);
    const submission = await api.post("/api/cet6/train/submissions", {
      kind: "translation", prompt_id: parent.prompt_id,
      mode: "rewrite", parent_id: id,
    });
    invalidate();
    const prompt = await api.get(
      `/api/cet6/train/prompts/${encodeURIComponent(parent.prompt_id)}?kind=translation`);
    renderEditor(submission, prompt);
  } catch (error) {
    toast(error.message || "开不了二稿", "err");
  }
}

export async function reviewAgain({ showWholeReviewing, id }) {
  try {
    const data = await api.post(`/api/cet6/train/submissions/${id}/review`, {});
    showWholeReviewing(id, data);
  } catch (error) {
    toast(error.message || "重批失败", "err");
  }
}

export async function saveScore({ panel, renderFeedback, id }) {
  const input = panel.querySelector("#cet6-score-input");
  const raw = input?.value?.trim() || "";
  try {
    const data = await api.post(
      `/api/cet6/train/submissions/${id}/external-score`,
      { score: raw === "" ? null : Number(raw) });
    renderFeedback(data);
    toast("已记录外部校准分", "ok");
  } catch (error) {
    toast(error.message || "分数没保存", "err");
  }
}
