// 到期复习窄提醒：句子和词分开计数，各自进英语复习对应 tab。
export function renderReminder(today) {
  const bar = document.getElementById("review-reminder");
  if (!bar) return;
  const sentence = Number(today?.due_sentence || 0);
  const word = Number(today?.due_word || 0);
  bar.hidden = sentence + word <= 0;
  const sentenceLink = document.getElementById("review-sentence-link");
  const wordLink = document.getElementById("review-word-link");
  const sentenceNum = document.getElementById("review-sentence-num");
  const wordNum = document.getElementById("review-word-num");
  if (sentenceNum) sentenceNum.textContent = String(sentence);
  if (wordNum) wordNum.textContent = String(word);
  if (sentenceLink) sentenceLink.hidden = sentence <= 0;
  if (wordLink) wordLink.hidden = word <= 0;
}

// 写作/翻译提升提醒：后端每天最多给一条，前端只负责显示，不再判断优先级。
export function renderCoach(coaching) {
  const bar = document.getElementById("coach-reminder");
  if (!bar) return;
  bar.hidden = !coaching;
  if (!coaching) return;
  const title = document.getElementById("coach-title");
  const detail = document.getElementById("coach-detail");
  const link = document.getElementById("coach-link");
  if (title) title.textContent = coaching.title || "";
  if (detail) detail.textContent = coaching.detail || "";
  if (link) {
    link.href = coaching.href || "#/cet6";
    link.textContent = `${coaching.label || "去完成"} →`;
  }
}
