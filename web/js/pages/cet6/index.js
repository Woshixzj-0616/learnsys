// 旧 #/cet6 入口的兜底 shim：真正的重定向在 `web/js/shell.js::legacyEnglishHash`。
// 正常情况下这个模块不会被加载；直接打开旧页面时，把它送回英语聚合页。
export async function mount() {
  location.replace("#/english");
}

export function unmount() {}
