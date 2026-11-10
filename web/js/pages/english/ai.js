// 六级训练通用 AI 助手门面：对外只暴露页面需要的接口。
// 抽屉外壳（圆圈 / 划词 / 开关 / 上下文）在 ai-dock.js；
// 会话、SSE 与历史在 ai-session.js。页面继续从 "./ai.js" 导入即可。
export {
  clearContextProvider, hasContext, mount, openAI, setContextProvider,
  setEnabled, setPage,
} from "./ai-dock.js";
