// 复习页键盘规则（纯函数，便于 node 测试）：
// 输入框里 Ctrl/Cmd+Enter 显示答案；看答案后 1–4 评档；空格/Enter 也能显示答案。
export function reviewKey(key, { revealed = false, typing = false, ctrl = false } = {}) {
  if (typing) {
    return ctrl && key === "Enter" ? "reveal" : "";
  }
  if (key === " " || key === "Enter") return revealed ? "" : "reveal";
  if (!revealed) return "";
  if (key === "1" || key === "2" || key === "3" || key === "4") {
    return `rate:${key}`;
  }
  return "";
}
