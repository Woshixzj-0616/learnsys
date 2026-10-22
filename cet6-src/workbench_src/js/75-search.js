// @requires: 00-core.js, 20-paper.js, 30-audio.js, 40-render.js, 50-actions.js
// 功能层：本卷句子搜索与跳转。
(function(WB){
  "use strict";

  const U = WB.util;
  let hits = [];
  let bound = false;

  function clear(){
    WB.dom.searchResults.classList.add("hidden");
    WB.dom.searchResults.innerHTML = "";
    hits = [];
  }

  function run(){
    const q = WB.dom.sentenceSearch.value.trim().toLowerCase();
    if(q.length < 2){ clear(); return; }
    hits = [];
    WB.session.paper.sections.forEach(function(sec, si){
      sec.items.forEach(function(cur, ii){
        cur.sentences.forEach(function(s){
          if((s.en || "").toLowerCase().indexOf(q) >= 0){
            hits.push({si:si, ii:ii, s:s, sec:sec.name, item:cur.title});
          }
        });
      });
    });
    WB.dom.searchResults.classList.remove("hidden");
    if(!hits.length){
      WB.dom.searchResults.innerHTML = '<p class="search-empty">没有匹配的句子</p>';
      return;
    }
    WB.dom.searchResults.innerHTML = hits.slice(0, 40).map(function(h, k){
      return '<button class="search-item" data-k="' + k + '">' +
        '<span class="m">' + U.escapeHtml(h.sec) + " / " + U.escapeHtml(h.item) +
          " · 第 " + h.s.i + " 句</span>" +
        '<span class="t">' + U.escapeHtml(h.s.en) + "</span></button>";
    }).join("") + (hits.length > 40
      ? '<p class="search-empty">仅显示前 40 条，共 ' + hits.length + " 条</p>" : "");
  }

  function init(){
    if(bound) return;
    bound = true;

    WB.dom.sentenceSearch.addEventListener("input", run);
    WB.dom.sentenceSearch.addEventListener("keydown", function(e){
      if(e.key === "Escape"){
        WB.dom.sentenceSearch.value = "";
        clear();
        WB.dom.sentenceSearch.blur();
      }
    });
    WB.dom.searchResults.addEventListener("click", function(e){
      const btn = e.target.closest("button[data-k]");
      if(!btn) return;
      const h = hits[Number(btn.dataset.k)];
      if(!h) return;
      WB.actions.selectItem(h.si, h.ii);
      clear();
      WB.dom.sentenceSearch.value = "";
      setTimeout(function(){
        const card = WB.dom.sentences.querySelector('.card[data-i="' + h.s.i + '"]');
        if(card){
          card.scrollIntoView({block:"center", behavior:"smooth"});
          card.classList.add("hit");
          setTimeout(function(){ card.classList.remove("hit"); }, 2200);
        }
        WB.audio.focusSentence(h.s.i);
      }, 60);
    });
  }

  WB.search = {init: init, clear: clear};
})(window.WB = window.WB || {});
