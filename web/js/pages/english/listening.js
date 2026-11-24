// 精听标签：原工作台 iframe，query 原样转发（paper 深链不回归）。
export function mountListening(panel, query) {
  const params = new URLSearchParams(query || "");
  params.delete("tab");
  const extra = params.toString();
  const src = `/cet6/工作台/精听工作台.html?v=20261119a${extra ? `&${extra}` : ""}`;
  panel.innerHTML = `<iframe class="cet6-frame" src="${src}"
    title="六级精听工作台"></iframe>`;

  // CET6 是外部 App：内置 AI 标记 legacy，这里只做宿主侧隐藏，
  // 不改外部 HTML（Phase 3 重建时再删）。同源才注入，跨源静默跳过。
  const frame = panel.querySelector("iframe.cet6-frame");
  const hideLegacyAI = () => {
    try {
      const doc = frame?.contentDocument;
      if (!doc || doc.getElementById("learnsys-hide-legacy-ai")) return;
      const style = doc.createElement("style");
      style.id = "learnsys-hide-legacy-ai";
      style.textContent = [
        "#askBtn", "#selAskBtn", "#askPanel", ".ai-fab", ".ai-dock",
        ".sel-ask", 'button[data-act="ask"]',
      ].map((selector) => `${selector}{display:none!important}`).join("\n");
      doc.head.appendChild(style);
      doc.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey)
            && String(event.key).toLowerCase() === "j") {
          event.preventDefault();
          event.stopImmediatePropagation();
        }
      }, true);
    } catch {
      /* 跨源 / 文档没就绪：不影响精听本体 */
    }
  };
  frame?.addEventListener("load", hideLegacyAI);
  if (frame?.contentDocument?.readyState === "complete") hideLegacyAI();
  return () => { panel.innerHTML = ""; };
}
