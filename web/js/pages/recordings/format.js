// 录像页的小格式化：时长 / 文件大小 / 日期。
export function secondsText(value) {
  const total = Math.max(0, Math.round(Number(value) || 0));
  if (total >= 3600) {
    return `${Math.floor(total / 3600)}:${String(Math.floor(total % 3600 / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  }
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export function bytesText(value) {
  let size = Math.max(0, Number(value) || 0);
  for (const unit of ["B", "KB", "MB", "GB"]) {
    if (size < 1024 || unit === "GB") {
      return unit === "B" ? `${Math.round(size)} B` : `${size.toFixed(1)} ${unit}`;
    }
    size /= 1024;
  }
  return `${size.toFixed(1)} GB`;
}

export function dateText(value) {
  const raw = String(value || "");
  return raw.length >= 16 ? raw.slice(5, 16) : raw;
}
