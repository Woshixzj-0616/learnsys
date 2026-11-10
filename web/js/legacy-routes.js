// 旧 hash 收口：纯函数，壳层与前端测试共用。
// 只做路由映射，不碰 DOM；`#/cet6` 是历史入口，统一去 `#/english`。
export function legacyEnglishHash(id, query) {
  if (id !== "cet6") return "";
  const rest = new URLSearchParams(query || "");
  const tab = String(rest.get("tab") || "");
  rest.delete("tab");
  const out = new URLSearchParams();
  if (tab === "writing") {
    out.set("tab", "writing");
    out.set("sub", "writing");
  } else if (tab === "translation") {
    out.set("tab", "writing");
    out.set("sub", "translation");
  } else if (tab === "review") {
    out.set("tab", "review");
  } else if (tab === "stats") {
    out.set("tab", "stats");
  } else {
    // 精听、已退休的 drill/chunk/exam、带 paper 的断点链接都落到精听。
    out.set("tab", "listening");
  }
  for (const [key, value] of rest) out.append(key, value);
  return `#/english?${out.toString()}`;
}
