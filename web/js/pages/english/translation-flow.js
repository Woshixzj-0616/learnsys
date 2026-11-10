// 翻译页的提交状态机：开练 → 批改中 → 已批改 / 失败，以及单句审核。
// 只负责状态转移与请求；具体视图由页面通过 page 回调（renderFeedback 等）渲染。
import { api } from "../../api.js";
import { escapeHtml, toast } from "../../ui.js";
import { pollSubmission } from "./poll.js";
import { progressHtml, sentenceResultHtml } from "./translation-views.js";
import { invalidate, markSentenceAttempted } from "./translation-data.js";

export async function startWhole(page, promptId, mode) {
  try {
    const [prompt, submission] = await Promise.all([
      api.get(`/api/cet6/train/prompts/${encodeURIComponent(promptId)}?kind=translation`),
      api.post("/api/cet6/train/submissions", {
        kind: "translation", prompt_id: promptId, mode,
      }),
    ]);
    invalidate();
    page.renderEditor(submission, prompt);
  } catch (error) {
    toast(error.message || "没能开始翻译", "err");
  }
}

export function showWholeReviewing(page, id, initial) {
  page.destroyEditor();
  page.clearPoll();
  invalidate();
  const handle = (data) => {
    if (data.status === "reviewed") {
      page.renderFeedback(data);
      return true;
    }
    if (data.status === "failed") {
      page.renderFailed(data);
      return true;
    }
    return false;
  };
  page.view = "review";
  if (handle(initial)) return;
  page.panel.innerHTML = progressHtml(id);
  page.poller = pollSubmission(id, {
    onTick: (seconds) => {
      const node = page.panel?.querySelector(".cet6-progress .hint");
      if (node) node.textContent = `已等待 ${seconds} 秒`;
    },
    onReviewed: (data) => page.renderFeedback(data),
    onFailed: (data) => page.renderFailed(data),
    onTimeout: () => {
      page.panel.innerHTML = '<div class="cet6-progress"><h2>还在批改</h2><p>稍后从「历史」打开这次提交。</p></div>';
    },
    onError: (error) => {
      page.panel.innerHTML = `<div class="cet6-progress"><h2>查询失败</h2>
        <p>${escapeHtml(error.message)}</p>
        <div class="cet6-actions"><button class="btn" type="button"
          data-act="open-sub" data-id="${id}">重试</button></div></div>`;
    },
  });
}

export async function openSubmission(page, id) {
  page.panel.innerHTML = '<div class="empty">正在打开这次提交…</div>';
  try {
    const detail = await api.get(`/api/cet6/train/submissions/${id}`);
    page.current = detail;
    if (detail.status === "reviewed") {
      page.renderFeedback(detail);
    } else if (detail.status === "reviewing") {
      showWholeReviewing(page, id, detail);
    } else if (detail.status === "failed") {
      page.renderFailed(detail);
    } else {
      const prompt = await api.get(
        `/api/cet6/train/prompts/${encodeURIComponent(detail.prompt_id)}?kind=translation`);
      page.renderEditor(detail, prompt);
    }
  } catch (error) {
    toast(error.message || "打开失败", "err");
  }
}

export async function editSubmission(page, id) {
  try {
    const detail = await api.get(`/api/cet6/train/submissions/${id}`);
    const prompt = await api.get(
      `/api/cet6/train/prompts/${encodeURIComponent(detail.prompt_id)}?kind=translation`);
    page.renderEditor(detail, prompt);
  } catch (error) {
    toast(error.message || "打开失败", "err");
  }
}

export async function submitSentence(page) {
  const textarea = page.panel.querySelector("#cet6-sentence-text");
  const text = textarea?.value?.trim() || "";
  if (!text) {
    toast("先写一句英文再提交", "err");
    return;
  }
  const box = page.panel.querySelector("#cet6-sentence-result");
  box.innerHTML = '<p class="hint">正在审核…</p>';
  try {
    const data = await api.post(
      `/api/cet6/train/sentences/${encodeURIComponent(page.sentence.id)}/review`,
      { text, pasted_chars: 0, left_seconds: 0 });
    page.sentenceResult = data;
    page.sentence.attempted = true;
    markSentenceAttempted(page.sentence.id);
    box.innerHTML = sentenceResultHtml(data);
    page.ctx.setSub(`翻译 · 一句一译 · ${page.sentence.skill || ""}`);
  } catch (error) {
    box.innerHTML = `<p class="cet6-warn">${escapeHtml(error.message || "审核失败")}</p>`;
  }
}
