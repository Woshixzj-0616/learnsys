// 页面模式：气质 / 专注 / 场景 / 视图 / 密度。
// 唯一状态落点；页面订阅 learnsys:modes 后自己决定怎么响应。
const KEY = "wb-modes";
const DEFAULTS = {
  mood: "mist",
  focus: false,
  scene: "study",
  view: "card",
  density: "comfortable",
};
const MOODS = ["mist", "ink", "paper"];
const THEME_COLOR = { mist: "#f3f5f9", ink: "#12151a", paper: "#f6f2ea" };

let state = { ...DEFAULTS };
try {
  const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
  if (saved && typeof saved === "object") state = { ...state, ...saved };
} catch { /* 坏数据就当没存过 */ }
if (!MOODS.includes(state.mood)) state.mood = "mist";
if (!["study", "work"].includes(state.scene)) state.scene = "study";
if (!["card", "list"].includes(state.view)) state.view = "card";
if (!["comfortable", "compact"].includes(state.density)) state.density = "comfortable";
state.focus = Boolean(state.focus);

// 深链/截图用：?mood=ink&scene=work&view=list&density=compact&focus=1
const params = new URLSearchParams(location.search);
if (MOODS.includes(params.get("mood"))) state.mood = params.get("mood");
if (["study", "work"].includes(params.get("scene"))) state.scene = params.get("scene");
if (["card", "list"].includes(params.get("view"))) state.view = params.get("view");
if (["comfortable", "compact"].includes(params.get("density"))) state.density = params.get("density");
if (params.get("focus") === "1") state.focus = true;
// 截图/演示用：?static=1 直接呈现最终帧
if (params.get("static") === "1") document.body.classList.add("static");

const body = document.body;
const modeBtn = document.getElementById("mode-btn");
const modePop = document.getElementById("mode-pop");

function persist() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* 隐身模式写不进去 */ }
}

function apply() {
  body.dataset.mood = state.mood;
  body.dataset.scene = state.scene;
  body.dataset.view = state.view;
  body.dataset.density = state.density;
  body.classList.toggle("focus", state.focus);

  document.querySelectorAll(".mood").forEach((node) => {
    node.classList.toggle("is-on", node.dataset.moodBtn === state.mood);
  });
  document.querySelectorAll(".seg button").forEach((node) => {
    const group = node.dataset.group;
    const on = group === "focus"
      ? (state.focus ? "on" : "off") === node.dataset.value
      : state[group] === node.dataset.value;
    node.classList.toggle("is-on", on);
  });

  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", THEME_COLOR[state.mood] || THEME_COLOR.mist);

  persist();
  window.dispatchEvent(new CustomEvent("learnsys:modes", { detail: { ...state } }));
}

export function getModes() {
  return { ...state };
}

function closePop() {
  if (!modePop) return;
  modePop.hidden = true;
  modeBtn?.setAttribute("aria-expanded", "false");
}

export function initModes() {
  apply();

  if (new URLSearchParams(location.search).get("panel") === "modes") {
    modePop.hidden = false;
    modeBtn?.setAttribute("aria-expanded", "true");
  }

  document.querySelectorAll(".mood").forEach((node) => {
    node.addEventListener("click", () => {
      state.mood = node.dataset.moodBtn;
      apply();
    });
  });

  modeBtn?.addEventListener("click", (event) => {
    event.stopPropagation();
    modePop.hidden = !modePop.hidden;
    modeBtn.setAttribute("aria-expanded", String(!modePop.hidden));
  });

  document.addEventListener("click", (event) => {
    if (!modePop || modePop.hidden) return;
    if (modePop.contains(event.target) || modeBtn?.contains(event.target)) return;
    closePop();
  });

  document.querySelectorAll(".seg button").forEach((node) => {
    node.addEventListener("click", () => {
      const group = node.dataset.group;
      const value = node.dataset.value;
      if (group === "focus") state.focus = value === "on";
      else state[group] = value;
      apply();
      if (state.focus) closePop();
    });
  });

  document.getElementById("focus-exit")?.addEventListener("click", () => {
    state.focus = false;
    apply();
  });

  document.getElementById("mode-reset")?.addEventListener("click", () => {
    state = { ...DEFAULTS };
    apply();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (modePop && !modePop.hidden) { closePop(); return; }
    if (state.focus) { state.focus = false; apply(); }
  });

  window.addEventListener("hashchange", closePop);
}

// 模块加载时就应用一次，避免首屏闪一下默认气质；交互绑定在 initModes。
apply();
