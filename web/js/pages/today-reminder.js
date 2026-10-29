// 到期复习窄提醒：只做提示，明细与评级都在错题本。
export function renderReminder(today) {
  const bar = document.getElementById("review-reminder");
  if (!bar) return;
  const due = Number(today?.due_reviews || 0);
  bar.hidden = due <= 0;
  const num = document.getElementById("review-due-num");
  if (num) num.textContent = String(due);
}
