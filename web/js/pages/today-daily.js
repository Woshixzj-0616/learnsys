// 今日页「每日积累」小卡：只展示三类进度与连续天数。
export function renderDaily(daily) {
  const card = document.getElementById("today-daily");
  if (!card) return;
  if (!daily || !Number(daily.total || 0)) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const labels = { writing: "写作", translation: "翻译", pron: "纠音" };
  const metrics = Object.entries(labels).map(([key, label]) => {
    const row = daily.counts?.[key] || { total: 0, done: 0 };
    return `<span><b>${label}</b> ${row.done}/${row.total}</span>`;
  }).join("");
  document.getElementById("daily-metrics").innerHTML =
    `${metrics}<span>连续 <b>${Number(daily.streak || 0)}</b> 天</span>`;
  const fill = document.getElementById("daily-bar-fill");
  if (fill) {
    const percent = daily.total
      ? Math.round(Number(daily.done || 0) * 100 / Number(daily.total)) : 0;
    fill.style.width = `${percent}%`;
  }
}
