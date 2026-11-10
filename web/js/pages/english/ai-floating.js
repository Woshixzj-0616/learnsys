// 六级 AI 的浮动入口：右下角圆圈可上下拖动；页面里选中文字浮出「问 AI」。
// 只做交互与选区检测，不碰会话与网络；位置记在 localStorage。
const FAB_KEY = "learnsys_cet6_ai_fab_top";

export function installFloating({ fab, sel, host, isEnabled, onToggle, onOpen, onSelect }) {
  const listeners = [];
  const bind = (target, type, fn, options) => {
    target.addEventListener(type, fn, options);
    listeners.push(() => target.removeEventListener(type, fn, options));
  };

  let drag = null;
  let suppressClick = false;
  let picked = "";

  const readTop = () => {
    try { return Number(localStorage.getItem(FAB_KEY)) || 0; } catch { return 0; }
  };
  const saveTop = (top) => {
    try { localStorage.setItem(FAB_KEY, String(Number(top) || 0)); } catch { /* 忽略 */ }
  };
  const clampTop = (top) => {
    const height = fab.offsetHeight || 54;
    return Math.min(Math.max(Number(top) || 0, 8), Math.max(8, window.innerHeight - height - 96));
  };
  const place = (top) => {
    fab.style.top = `${clampTop(top)}px`;
    fab.style.bottom = "auto";
  };
  const saved = readTop();
  if (saved) place(saved);

  // 圆圈只上下移动：左右仍然贴右边，避免挡住正文中间。
  bind(fab, "pointerdown", (event) => {
    if (event.button != null && event.button !== 0) return;
    const rect = fab.getBoundingClientRect();
    drag = { y: event.clientY, top: rect.top, moved: false, id: event.pointerId };
    try { fab.setPointerCapture(event.pointerId); } catch { /* 不支持就算了 */ }
  });
  bind(fab, "pointermove", (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    const delta = event.clientY - drag.y;
    if (Math.abs(delta) > 4) drag.moved = true;
    if (drag.moved) place(drag.top + delta);
  });
  bind(fab, "pointerup", (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    const moved = drag.moved;
    const top = fab.getBoundingClientRect().top;
    drag = null;
    try { fab.releasePointerCapture(event.pointerId); } catch { /* 忽略 */ }
    if (!moved) return;
    place(top);
    saveTop(clampTop(top));
    suppressClick = true;
    setTimeout(() => { suppressClick = false; }, 0);
  });
  bind(fab, "pointercancel", () => { drag = null; });
  bind(fab, "click", (event) => {
    if (suppressClick) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    onToggle();
  });

  bind(window, "resize", () => {
    const top = readTop();
    if (top && fab.style.bottom === "auto") place(top);
  });

  // ---- 划词「问 AI」 ----
  function hideSelection() {
    sel.hidden = true;
  }

  function onMouseUp(event) {
    if (!isEnabled()) return;
    if (event.target === sel || fab.contains(event.target)) return;
    setTimeout(() => {
      const selection = window.getSelection ? window.getSelection() : null;
      const text = String(selection?.toString() || "").trim();
      if (!text || text.length > 2000 || !selection.rangeCount
          || !host.contains(selection.anchorNode)) {
        hideSelection();
        return;
      }
      const rect = selection.getRangeAt(0).getBoundingClientRect();
      if (!rect.width && !rect.height) {
        hideSelection();
        return;
      }
      picked = text;
      onSelect(text);
      const left = Math.min(Math.max(rect.left + rect.width / 2, 70), window.innerWidth - 70);
      sel.style.left = `${left}px`;
      sel.style.top = `${Math.max(rect.top - 40, 8)}px`;
      sel.hidden = false;
    }, 0);
  }

  bind(host, "mouseup", onMouseUp);
  bind(host, "scroll", hideSelection, true);
  bind(document, "mousedown", (event) => {
    if (event.target !== sel) hideSelection();
  });
  bind(sel, "mousedown", (event) => event.preventDefault());
  bind(sel, "click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    onSelect(picked);
    hideSelection();
    onOpen();
  });

  return {
    hideSelection,
    cleanup() {
      for (const unbind of listeners.splice(0)) {
        try { unbind(); } catch { /* 忽略 */ }
      }
    },
  };
}
