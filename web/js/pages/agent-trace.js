// 调用路径：只读查看智能旅行 /api/chat 的 trace_log。
// 左边选一条请求，右边画「开轮 → 模型 → 工具 → 打回 → 审核 → 回答」。
// 渲染与字段字典在 agent-trace-render.js / agent-trace-docs.js；这里只管页面状态和网络。
import { api, health } from "../api.js";
import { escapeHtml } from "../ui.js";
import {
  detailEvents, pathHtml, rowHtml, summaryHtml, timelineHtml,
} from "./agent-trace-render.js";

let root = null;
let nodes = {};
let currentId = "";
let showCtx = false;
let travelToken = "";
let travelUser = "";
let travelBase = "http://127.0.0.1:8000";
let sending = false;
let messages = [];

const TOKEN_KEY = "learnsys.travel.token";
const USER_KEY = "learnsys.travel.user";
const BASE_KEY = "learnsys.travel.base";

function renderList(items) {
  if (!items.length) {
    nodes.list.innerHTML = `<div class="at-empty">还没有 /api/chat 记录。<br>先在智能旅行里问一句话，再回来刷新。</div>`;
    return;
  }
  nodes.list.innerHTML = items.map((item) => rowHtml(item, currentId)).join("");
}

async function load(username = "") {
  nodes.list.innerHTML = `<div class="at-empty">正在读 trace…</div>`;
  try {
    const suffix = username ? `&username=${encodeURIComponent(username)}` : "";
    const data = await api.get(`/api/agent-trace?limit=40${suffix}`);
    if (!data.ok) {
      nodes.list.innerHTML = `<div class="at-empty">${escapeHtml(data.why || "读不到旅行库")}<br>
        <span style="font-size:12px">库：${escapeHtml(data.db || "")}</span></div>`;
      nodes.detail.innerHTML = `<div class="at-empty">先确认智能旅行后端库存在，再回来刷新。</div>`;
      return;
    }
    const items = data.items || [];
    renderList(items);
    const keep = items.some((item) => item.trace_id === currentId);
    if (!keep) currentId = items.length ? items[0].trace_id : "";
    if (currentId) await select(currentId);
    else nodes.detail.innerHTML = `<div class="at-empty">还没有可看的请求。</div>`;
  } catch (error) {
    nodes.list.innerHTML = `<div class="at-empty">读 trace 失败：${escapeHtml(error?.message || error)}</div>`;
  }
}

function renderDetail(data) {
  const events = detailEvents(data.events || []);
  nodes.detail.innerHTML = `
    ${summaryHtml(data)}
    ${pathHtml(events)}
    <div class="at-card" style="padding:10px 13px">
      <div class="at-h"><span class="at-name">${escapeHtml(data.at)}</span><span class="at-desc">trace ${escapeHtml(data.trace_id)} · ${escapeHtml(data.path)} · 用户 ${escapeHtml(data.username)}</span></div>
    </div>
    <div class="at-toolbar"><h3>时间线</h3><label class="at-check"><input type="checkbox" id="at-all" ${showCtx ? "checked" : ""}> 显示上下文计量（ctx）</label></div>
    <ol class="at-timeline">${timelineHtml(events, showCtx)}</ol>`;
  const toggle = nodes.detail.querySelector("#at-all");
  if (toggle) {
    toggle.addEventListener("change", () => {
      showCtx = !!toggle.checked;
      const list = nodes.detail.querySelector(".at-timeline");
      if (list) list.innerHTML = timelineHtml(events, showCtx);
    });
  }
}

async function select(traceId) {
  currentId = traceId;
  const rows = nodes.list.querySelectorAll(".at-row");
  rows.forEach((row) => row.classList.toggle("on", row.dataset.id === currentId));
  nodes.detail.innerHTML = `<div class="at-empty">正在读 ${escapeHtml(traceId)}…</div>`;
  try {
    const data = await api.get(`/api/agent-trace/${encodeURIComponent(traceId)}`);
    renderDetail(data);
  } catch (error) {
    nodes.detail.innerHTML = `<div class="at-empty">读这条 trace 失败：${escapeHtml(error?.message || error)}</div>`;
  }
}

function authText() {
  return travelToken ? `已登录：${travelUser || "智能旅行"}` : "未登录智能旅行";
}

function updateAuth() {
  if (nodes.status) nodes.status.textContent = authText();
  if (nodes.loginToggle) nodes.loginToggle.textContent = travelToken ? "重新登录" : "登录";
  if (nodes.login) nodes.login.hidden = !!travelToken;
}

async function login() {
  const username = (nodes.user?.value || "").trim();
  const password = nodes.pass?.value || "";
  if (!username || !password) {
    nodes.loginStatus.textContent = "用户名和密码都要填";
    return;
  }
  nodes.loginStatus.textContent = "登录中…";
  try {
    const data = await api.post("/api/agent-trace/login", {
      username, password, base: travelBase,
    });
    travelToken = data.token || "";
    travelUser = data.username || username;
    localStorage.setItem(TOKEN_KEY, travelToken);
    localStorage.setItem(USER_KEY, travelUser);
    nodes.pass.value = "";
    nodes.loginStatus.textContent = "登录成功";
    updateAuth();
  } catch (error) {
    nodes.loginStatus.textContent = error?.message || String(error);
  }
}

function appendLive(text) {
  if (!nodes.liveBody) return;
  nodes.liveBody.textContent += text;
  nodes.liveBody.scrollTop = nodes.liveBody.scrollHeight;
}

async function readSse(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf("\n\n");
    while (cut >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of block.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        if (!raw || raw === "[DONE]") continue;
        let obj = null;
        try { obj = JSON.parse(raw); } catch { continue; }
        if (obj.proxy_error) {
          appendLive(`\n[代理出错] ${obj.proxy_error}\n`);
          nodes.liveStatus.textContent = "转发失败";
        } else if (obj.error) {
          appendLive(`\n[出错] ${obj.error}\n`);
          nodes.liveStatus.textContent = "这一轮出错";
        } else if (obj.delta) {
          answer += obj.delta;
          appendLive(obj.delta);
        } else if (obj.status) {
          nodes.liveStatus.textContent = obj.status;
        } else if (obj.trip) {
          appendLive("\n（收到行程表）\n");
        } else if (obj.notice) {
          appendLive(`\n[提示] ${obj.notice}\n`);
        }
      }
      cut = buffer.indexOf("\n\n");
    }
  }
  return answer;
}

async function send() {
  if (sending) return;
  const text = (nodes.input?.value || "").trim();
  if (!text) return;
  if (!travelToken) {
    nodes.login.hidden = false;
    nodes.status.textContent = "先登录智能旅行";
    return;
  }
  sending = true;
  nodes.send.disabled = true;
  nodes.live.hidden = false;
  nodes.liveBody.textContent = "";
  nodes.liveStatus.textContent = "正在发送…";
  appendLive(`你：${text}\n\n`);
  messages.push({ role: "user", content: text });
  try {
    const response = await fetch("/api/agent-trace/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Learnsys-Token": health().token || "",
        "X-Travel-Token": travelToken,
      },
      body: JSON.stringify({ base: travelBase, messages: messages.slice() }),
    });
    if (response.status === 401) {
      messages.pop();
      travelToken = "";
      localStorage.removeItem(TOKEN_KEY);
      updateAuth();
      nodes.liveStatus.textContent = "登录已失效，请重新登录";
      return;
    }
    if (!response.ok) {
      messages.pop();
      nodes.liveStatus.textContent = `请求失败（${response.status}）`;
      appendLive(await response.text());
      return;
    }
    const answer = await readSse(response);
    if (answer) messages.push({ role: "assistant", content: answer });
    nodes.liveStatus.textContent = "完成";
    nodes.input.value = "";
    // trace_log 是请求结束后才落库的，稍等一下再刷新列表；并强制看最新一条
    await new Promise((resolve) => setTimeout(resolve, 1200));
    currentId = "";
    await load(travelUser);
  } catch (error) {
    messages.pop();
    nodes.liveStatus.textContent = "转发失败";
    appendLive(`\n${error?.message || error}\n`);
  } finally {
    sending = false;
    if (nodes.send) nodes.send.disabled = false;
  }
}

function newChat() {
  messages = [];
  if (nodes.input) nodes.input.value = "";
  if (nodes.liveBody) nodes.liveBody.textContent = "";
  if (nodes.liveStatus) nodes.liveStatus.textContent = "新对话";
}

export async function mount(ctx) {
  ctx.setSub("输入一句话发给智能旅行 agent，或从左边选一条历史请求看它的调用路径。");
  root = ctx.root;
  nodes = {
    list: root.querySelector("#at-list"),
    detail: root.querySelector("#at-detail"),
    refresh: root.querySelector("#at-refresh"),
    input: root.querySelector("#at-input"),
    send: root.querySelector("#at-send"),
    status: root.querySelector("#at-status"),
    loginToggle: root.querySelector("#at-login-toggle"),
    login: root.querySelector("#at-login"),
    user: root.querySelector("#at-user"),
    pass: root.querySelector("#at-pass"),
    loginBtn: root.querySelector("#at-login-btn"),
    loginStatus: root.querySelector("#at-login-status"),
    live: root.querySelector("#at-live"),
    liveStatus: root.querySelector("#at-live-status"),
    liveBody: root.querySelector("#at-live-body"),
    liveClear: root.querySelector("#at-live-clear"),
    newChat: root.querySelector("#at-new"),
    base: root.querySelector("#at-base"),
  };
  travelToken = localStorage.getItem(TOKEN_KEY) || "";
  travelUser = localStorage.getItem(USER_KEY) || "";
  travelBase = localStorage.getItem(BASE_KEY) || "http://127.0.0.1:8000";
  if (nodes.base) nodes.base.value = travelBase;
  updateAuth();
  nodes.refresh?.addEventListener("click", () => load());
  nodes.list?.addEventListener("click", (event) => {
    const row = event.target.closest(".at-row");
    if (row && row.dataset.id) select(row.dataset.id);
  });
  nodes.loginToggle?.addEventListener("click", () => {
    nodes.login.hidden = !nodes.login.hidden;
  });
  nodes.loginBtn?.addEventListener("click", login);
  nodes.send?.addEventListener("click", send);
  nodes.newChat?.addEventListener("click", newChat);
  nodes.input?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) send();
  });
  nodes.base?.addEventListener("change", () => {
    travelBase = (nodes.base.value || "").trim() || "http://127.0.0.1:8000";
    localStorage.setItem(BASE_KEY, travelBase);
  });
  nodes.liveClear?.addEventListener("click", () => {
    nodes.liveBody.textContent = "";
    nodes.liveStatus.textContent = "已清空";
  });
  await load();
}

export function unmount() {
  root = null;
  nodes = {};
  currentId = "";
  showCtx = false;
  messages = [];
}
