// @requires: 00-core.js, 10-storage.js
// 主题层：浅色 / 深色切换的唯一交互落点。
// 首屏的 data-theme 由 shell.html 内联脚本先设好（避免闪白），这里只负责按钮与持久化。
(function(WB){
  "use strict";

  var current = "dark";

  function apply(theme, persist){
    current = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", current);
    document.querySelectorAll("[data-theme-set]").forEach(function(btn){
      var on = btn.dataset.themeSet === current;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
    var meta = document.querySelector('meta[name="theme-color"]');
    if(meta) meta.setAttribute("content", current === "dark" ? "#12171a" : "#f7f4ee");
    if(persist) WB.store.saveTheme(current);
  }

  function init(){
    var buttons = document.querySelectorAll("[data-theme-set]");
    if(!buttons.length) return;
    buttons.forEach(function(btn){
      btn.addEventListener("click", function(){
        apply(btn.dataset.themeSet, true);
      });
    });
    apply(WB.store.loadTheme(), false);
  }

  WB.theme = {
    init: init,
    apply: apply,
    current: function(){ return current; }
  };
})(window.WB = window.WB || {});
