// 写作 / 翻译两个大页面的 AI 上下文装配：页面只传状态，模板放在这里，
// 避免 translation.js / writing.js 再把体量顶到红线以上。

export function writingContext({ editor, current, currentPrompt, view, panel }) {
  if (editor) {
    const prompt = currentPrompt || {};
    const text = panel?.querySelector("#cet6-text")?.value || "";
    return {
      object_type: "cet6_writing_draft",
      object_id: String(current?.id || prompt.id || ""),
      title: `六级写作 · ${prompt.title || "正在写"}`,
      surrounding: {
        题目: prompt.prompt_en || "",
        中文提示: prompt.prompt_zh || "",
        给定首句: prompt.lead_sentence || "",
        审题角度: (prompt.angle_points || []).join("；"),
        我的草稿: text,
      },
      learning_state: {
        模式: current?.mode === "timed" ? "限时" : "练习",
        字数: text.trim() ? text.trim().split(/\s+/).length : 0,
      },
    };
  }
  if (current && (view === "feedback" || view === "failed")) {
    const review = current.review || {};
    return {
      object_type: "cet6_writing_review",
      object_id: String(current.id || ""),
      title: `六级写作批改 · ${current.title || ""} · ${current.band ?? "—"} 档`,
      surrounding: {
        题目: current.title || "",
        我的原文: String(current.text || "").slice(0, 1500),
        档位理由: review.band_reason || "",
      },
      learning_state: {
        档位: current.band ?? "—",
        优先修改: (review.priorities || []).join("；"),
        错误清单: (review.errors || []).slice(0, 8).map((row) =>
          `${row.type || "错误"}：${row.quote || ""} → ${row.fix || ""}`).join("\n"),
      },
    };
  }
  const pages = { home: "今日", library: "题库", history: "历史", prompt: "题目" };
  return {
    object_type: "cet6_writing",
    object_id: view,
    title: `六级写作 · ${pages[view] || "训练"}`,
    surrounding: { 当前题目: currentPrompt?.title || current?.title || "" },
    learning_state: {},
  };
}

export function translationContext({ view, current, sentence, sentenceResult, panel }) {
  if (view === "sentence" && sentence) {
    const text = panel?.querySelector("#cet6-sentence-text")?.value || "";
    const review = sentenceResult?.review || null;
    return {
      object_type: "cet6_translation_sentence",
      object_id: String(sentence.id || ""),
      title: `六级翻译一句一译 · ${sentence.skill || ""}`
        + (sentence.source_title ? ` · ${sentence.source_title}` : ""),
      surrounding: {
        中文原句: sentence.zh || "",
        你的译文: text,
        参考译文: review?.reference || "",
      },
      learning_state: review ? {
        结论: review.conclusion || "已审核",
        信息点: `${review.info_points?.covered ?? "—"} / ${review.info_points?.total ?? "—"}`,
        必改: (review.must_fix || []).map((row) =>
          `${row.quote || ""} → ${row.fix || ""}`).join("；"),
      } : { 状态: "未提交" },
    };
  }
  if (current && (view === "feedback" || view === "failed" || view === "sentence-attempt")) {
    const review = current.review || {};
    const item = current.sentence || {};
    return {
      object_type: "cet6_translation_review",
      object_id: String(current.id || ""),
      title: `六级翻译批改 · ${current.title || item.skill || "翻译"} · ${current.band ?? "—"} 档`,
      surrounding: {
        题目: current.title || item.zh || "",
        我的译文: String(current.text || "").slice(0, 1500),
        参考译文: current.reference || review.reference || "",
      },
      learning_state: {
        档位: current.band ?? "—",
        结论: review.conclusion || "",
        优先修改: (review.priorities || []).join("；"),
        错误清单: (review.errors || []).slice(0, 8).map((row) =>
          `${row.type || "错误"}：${row.quote || ""} → ${row.fix || ""}`).join("\n"),
      },
    };
  }
  const pages = { home: "今日", library: "题库", terms: "术语", history: "历史" };
  return {
    object_type: "cet6_translation",
    object_id: view,
    title: `六级翻译 · ${pages[view] || "训练"}`,
    surrounding: {},
    learning_state: {},
  };
}
