// 统计页的纯格式化函数（不碰 DOM，便于 node 测试）。
export const BAND_MAX = 15;

export function bandText(value) {
  return value === null || value === undefined || value === ""
    || Number.isNaN(Number(value))
    ? "—" : String(value);
}

export function bandWidth(value) {
  const band = Number(value);
  if (!Number.isFinite(band)) return 0;
  return Math.max(0, Math.min(100, Math.round((band / BAND_MAX) * 100)));
}

export function formatMinutes(minutes) {
  const value = Number(minutes) || 0;
  if (value < 60) return `${Math.round(value)} 分钟`;
  return `${(value / 60).toFixed(1)} 小时`;
}

export function overallBand(byKind) {
  let total = 0;
  let weight = 0;
  for (const kind of ["writing", "translation"]) {
    const row = byKind?.[kind] || {};
    const count = Number(row.submissions) || 0;
    const band = Number(row.avg_band);
    if (count && Number.isFinite(band)) {
      total += band * count;
      weight += count;
    }
  }
  return weight ? Math.round((total / weight) * 10) / 10 : null;
}

export function trendBar(value) {
  if (value === null || value === undefined || value === "") {
    return { text: "—", width: 0, level: "none" };
  }
  const band = Number(value);
  return {
    text: bandText(value),
    width: bandWidth(value),
    level: !Number.isFinite(band) ? "none"
      : band >= 13 ? "high" : band >= 10 ? "mid" : "low",
  };
}
