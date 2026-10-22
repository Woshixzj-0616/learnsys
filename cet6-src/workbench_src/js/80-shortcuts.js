// @requires: 00-core.js, 30-audio.js, 50-actions.js
// 交互层：全局键盘快捷键。
(function(WB){
  "use strict";

  let bound = false;

  function init(){
    if(bound) return;
    bound = true;

    document.addEventListener("keydown", function(e){
      const t = e.target;
      if(t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" ||
               t.tagName === "SELECT" || t.isContentEditable)) return;
      if((e.ctrlKey || e.metaKey) && (e.key === "j" || e.key === "J")){
        e.preventDefault();
        if(WB.ask && WB.ask.togglePanel) WB.ask.togglePanel();
        return;
      }
      if(e.ctrlKey || e.metaKey || e.altKey) return;

      if(e.key === " "){
        e.preventDefault();
        if(WB.session.activeSentence >= 0) WB.audio.toggleSentence(WB.session.activeSentence);
        else if(WB.audio.isPaused()) WB.audio.safePlay();
        else WB.dom.audio.pause();
      }else if(e.key === "ArrowUp"){
        e.preventDefault();
        WB.audio.moveSentence(-1);
      }else if(e.key === "ArrowDown"){
        e.preventDefault();
        WB.audio.moveSentence(1);
      }else if(e.key === "ArrowLeft" || e.key === "ArrowRight"){
        // 原生播放器默认一次 5 秒，对精听太粗；这里改成 1 秒，Shift 才 5 秒。
        e.preventDefault();
        const step = e.shiftKey ? 5 : 1;
        WB.audio.seekBy(e.key === "ArrowRight" ? step : -step);
        WB.status("已" + (e.key === "ArrowRight" ? "前进" : "后退") +
          " " + step + " 秒。");
      }else if(e.key === "r" || e.key === "R"){
        e.preventDefault();
        WB.audio.replayActive();
      }else if(e.key === "l" || e.key === "L"){
        e.preventDefault();
        WB.actions.toggleLoopActive();
      }else if(e.key === "d" || e.key === "D"){
        e.preventDefault();
        WB.actions.toggleDoneActive();
      }else if(/^[1-5]$/.test(e.key)){
        e.preventDefault();
        WB.actions.toggleTagActive(Number(e.key) - 1);
      }else if(e.key === "/"){
        e.preventDefault();
        WB.dom.sentenceSearch.focus();
      }
    });
  }

  WB.shortcuts = {init: init};
})(window.WB = window.WB || {});
