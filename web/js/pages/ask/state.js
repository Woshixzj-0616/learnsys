// 问一问页面的共享状态：所有子模块 import 同一个对象，别各存一份。
export const MODE_NAMES = { explain: "讲解", guide: "引导", quiz: "测验", quick: "速答" };
export const TOOL_NAMES = {
  search_records: "查本地记录",
  today_summary: "看今日概览",
  recent_wrong_items: "查错题本",
  read_attachment: "读文档",
  ocr_image: "OCR 看图",
  search_materials: "搜资料库",
  read_material: "读资料",
  get_cet6_context: "读六级进度",
  save_wrongbook: "收错题",
  save_memory: "记长期偏好",
  forget_memory: "忘掉记忆",
  save_material_note: "存资料笔记",
  write_study_file: "写学习档案",
  run_code: "运行代码",
  open_file: "打开文件",
  launch_app: "启动程序",
  open_url: "打开网址",
  browser_status: "看浏览器状态",
  browser_history: "读浏览记录",
};

export const state = {
  mounted: false,
  conversations: [],
  convId: null,
  messages: [],
  streaming: false,
  controller: null,
  timer: 0,
  image: null,
  doc: null,
  material: null,
  materialPinned: false,
  mode: "explain",
  assistant: null,
  text: "",
  thinking: "",
  startedAt: 0,
  runId: "",
  usedTools: new Set(),
  usedVision: false,
  stopped: false,
  thinkingDirty: false,
};

export let dom = {};
export let ctxRef = null;

export function setCtx(ctx) {
  ctxRef = ctx;
}

export function setDom(next) {
  dom = next;
}

export function resetState() {
  Object.assign(state, {
    mounted: false,
    conversations: [],
    convId: null,
    messages: [],
    streaming: false,
    controller: null,
    timer: 0,
    image: null,
    doc: null,
    material: null,
    materialPinned: false,
    mode: localStorage.getItem("learnsys_mode") || "explain",
    assistant: null,
    text: "",
    thinking: "",
    startedAt: 0,
    runId: "",
    usedTools: new Set(),
    usedVision: false,
    stopped: false,
    thinkingDirty: false,
  });
}

export function setSubDefault() {
  ctxRef?.setSub("同一个 Agent：横栏、工作台共用提示词、工具和记录");
}
