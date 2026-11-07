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
