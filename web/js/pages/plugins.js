// 插件中心：列出全部插件、开关、打开；开关写回 设置.json 的 modules。
import { api } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

let ctxRef = null;
let modules = [];
let prefs = {};

export async function mount(ctx) {
  ctxRef = ctx;
  ctx.setSub("启停插件、看清单、进入口");
  ctx.setActions("");
  const [registry, settings] = await Promise.all([
    api.get("/api/modules"),
    api.get("/api/settings").catch(() => ({ modules: {} })),
  ]);
  modules = Array.isArray(registry.modules) ? registry.modules : [];
  prefs = settings.modules || {};
  render();
}

function render() {
  const ready = modules.filter((m) => m.status !== "planned").length;
  const enabled = modules.filter((m) => prefs[m.id] !== false).length;
  document.getElementById("plugins-summary").innerHTML = `
    <div class="stat"><div class="stat-label">插件</div>
      <div class="stat-value">${modules.length}<small>个</small></div>
      <div class="stat-note">${ready} 个可用</div></div>
    <div class="stat"><div class="stat-label">已启用</div>
      <div class="stat-value">${enabled}<small>个</small></div>
      <div class="stat-note">关闭只是隐藏入口</div></div>`;

  document.getElementById("plugin-list").innerHTML = modules.map((m) => {
    const planned = m.status === "planned";
    const checked = prefs[m.id] !== false ? "checked" : "";
    return `<article class="plugin-row${planned ? " planned" : ""}">
      <span class="plugin-row-icon" aria-hidden="true">${escapeHtml(m.icon || "·")}</span>
      <div class="plugin-row-main">
        <div class="plugin-row-title">
          <strong>${escapeHtml(m.name)}</strong>
          <span class="plugin-version">v${escapeHtml(m.version || "2.0.0")}</span>
          <span class="plugin-cat">${escapeHtml(m.category || "插件")}</span>
          ${planned ? '<span class="nav-flag">待建</span>' : ""}
        </div>
        <p>${escapeHtml(m.description || m.note || "")}</p>
        <p class="hint">${escapeHtml(m.tagline || "")}</p>
      </div>
      <div class="plugin-row-actions">
        ${planned ? "" : `<button class="btn" type="button" data-open="${escapeHtml(m.id)}">打开</button>`}
        <label class="switch" title="启用 / 关闭这个插件">
          <input type="checkbox" data-toggle="${escapeHtml(m.id)}" ${checked}>
          <span>${checked ? "启用" : "关闭"}</span>
        </label>
      </div>
    </article>`;
  }).join("");

  document.querySelectorAll("[data-open]").forEach((node) => {
    node.addEventListener("click", () => { location.hash = `#/${node.dataset.open}`; });
  });
  document.querySelectorAll("[data-toggle]").forEach((node) => {
    node.addEventListener("change", async () => {
      const id = node.dataset.toggle;
      const enabled = node.checked;
      const before = prefs[id] !== false;
      prefs[id] = enabled;
      const label = node.parentElement?.querySelector("span");
      if (label) label.textContent = enabled ? "启用" : "关闭";
      window.dispatchEvent(new CustomEvent("learnsys:prefs", { detail: { [id]: enabled } }));
      try {
        await api.post("/api/settings", { modules: { [id]: enabled } });
        toast(`${enabled ? "已启用" : "已关闭"}插件`, "ok");
      } catch (error) {
        prefs[id] = before;
        node.checked = before;
        if (label) label.textContent = before ? "启用" : "关闭";
        window.dispatchEvent(new CustomEvent("learnsys:prefs", { detail: { [id]: before } }));
        toast(error.message || "插件开关没保存", "err");
      }
      renderSummary();
    });
  });
}

function renderSummary() {
  const enabled = modules.filter((m) => prefs[m.id] !== false).length;
  const stats = document.querySelectorAll("#plugins-summary .stat-value");
  if (stats[1]) stats[1].innerHTML = `${enabled}<small>个</small>`;
}
