// @requires: 00-core.js
// 运行模式：HTTP / file:// 与「退休后只读」的唯一判断处。
// 退休开关是构建常量 WB.FLAGS.retired（在 00-core.js），11-04 凭报告改 true 后重建。
(function(WB){
  "use strict";

  const HTTP = location.protocol === "http:" || location.protocol === "https:";
  const FLAGS = WB.FLAGS || (WB.FLAGS = {retired:false});

  const mode = {
    HTTP: HTTP,
    retired: !!FLAGS.retired,
    // file:// 是旧入口；退休后只读。HTTP 模式永远可写。
    readOnly: !!FLAGS.retired && !HTTP,
    // syncPaper 读取服务端进度期间，4 个同步字段先别让改。
    hydrating: false,

    ensureWritable: function(what){
      if(!mode.readOnly) return true;
      const label = what ? "（" + what + "）" : "";
      if(WB.status) WB.status("只读模式" + label + "：请从学习工作台打开后再修改。");
      return false;
    },

    banner: function(text){
      if(!text) return;
      const show = function(){
        let el = document.getElementById("modeBanner");
        if(!el){
          el = document.createElement("div");
          el.id = "modeBanner";
          el.className = "mode-banner";
          el.setAttribute("role", "status");
          const wrap = document.querySelector(".wrap") || document.body;
          wrap.insertBefore(el, wrap.firstChild);
        }
        el.textContent = text;
        el.classList.remove("hidden");
      };
      if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", show);
      else show();
    }
  };

  if(mode.readOnly){
    mode.banner("只读模式 · 进度以学习系统为准 · 可以查看和导出，不能修改。");
  }
  WB.cet6Mode = mode;
})(window.WB = window.WB || {});
