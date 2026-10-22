// @requires: 00-core.js, 10-storage.js, 20-paper.js, 40-render.js, 55-api.js
// 翻译层：划词查词（含音标/释义，可一键进生词本）+ 逐句译文开关。
// 译文按题型单元缓存在 state.translation，刷新后直接显示，不再请求模型。
(function(WB){
  "use strict";

  const U = WB.util;
  let bound = false;
  let lastSelection = "";
  let lastInfo = null;

  function currentSelection(){
    const selObj = window.getSelection ? window.getSelection() : null;
    const sel = selObj ? String(selObj.toString() || "").trim() : "";
    if(!sel || sel.length > 60 || !selObj.anchorNode) return null;
    const node = selObj.anchorNode;
    const el = node.nodeType === 1 ? node : node.parentElement;
    const en = el && el.closest ? el.closest(".en") : null;
    if(!en) return null;
    let rect = null;
    try{ rect = selObj.getRangeAt(0).getBoundingClientRect(); }catch(e){ return null; }
    const card = el.closest(".card");
    const i = card ? Number(card.dataset.i) : -1;
    const sentence = i >= 0 ? WB.paper.findSentence(i) : null;
    return {text: sel, rect: rect, sentence: sentence ? sentence.en : "",
            i: i, card: card};
  }

  function place(btn, left, top){
    if(!btn) return;
    btn.style.left = Math.max(8, Math.min(window.innerWidth - 108, left)) + "px";
    btn.style.top = Math.max(8, top) + "px";
  }

  function updateSelectionButton(){
    const info = currentSelection();
    const vocabBtn = WB.dom.selVocabBtn;
    const transBtn = WB.dom.selTranslateBtn;
    const askBtn = WB.dom.selAskBtn;
    if(!info || !info.text){
      if(vocabBtn) vocabBtn.classList.add("hidden");
      if(transBtn) transBtn.classList.add("hidden");
      if(askBtn) askBtn.classList.add("hidden");
      lastSelection = "";
      return;
    }
    lastSelection = info.text;
    lastInfo = info;
    const center = info.rect.left + info.rect.width / 2;
    const left = Math.max(8, Math.min(window.innerWidth - 190, center - 90));
    place(vocabBtn, left, info.rect.top - 36);
    place(transBtn, left + 64, info.rect.top - 36);
    place(askBtn, left + 116, info.rect.top - 36);
    if(vocabBtn) vocabBtn.classList.remove("hidden");
    if(transBtn) transBtn.classList.remove("hidden");
    if(askBtn) askBtn.classList.remove("hidden");
  }

  function showPopover(rect, html){
    const pop = WB.dom.translationPop;
    if(!pop) return;
    pop.innerHTML = html;
    pop.classList.remove("hidden");
    const width = 320;
    const left = Math.max(8, Math.min(window.innerWidth - width - 12,
      rect.left + rect.width / 2 - width / 2));
    let top = rect.bottom + 8;
    if(top + 190 > window.innerHeight) top = Math.max(8, rect.top - 198);
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }

  function hidePopover(){
    if(WB.dom.translationPop) WB.dom.translationPop.classList.add("hidden");
  }

  function kindOf(text){
    if(/[.!?。！？;；]$/.test(text) || text.length > 36) return "sentence";
    return "word";
  }

  async function translateSelection(){
    const info = currentSelection() || lastInfo || {
      text: lastSelection, rect: {left: window.innerWidth / 2, bottom: 80,
                                  top: 40, width: 0}, sentence: "", i: -1
    };
    if(!info.text) return;
    if(WB.dom.selVocabBtn) WB.dom.selVocabBtn.classList.add("hidden");
    if(WB.dom.selTranslateBtn) WB.dom.selTranslateBtn.classList.add("hidden");
    const sec = WB.paper.currentSection();
    const cur = WB.paper.currentItem();
    const infoPaper = WB.session.paperDir || WB.session.paper.title;
    showPopover(info.rect, '<p class="status">翻译中…</p>');
    if(!WB.api || !WB.api.ready){
      showPopover(info.rect,
        '<p class="status">划词翻译需要从学习工作台打开（HTTP /cet6/）。</p>' +
        '<div class="trans-actions"><button data-trans="close">关闭</button></div>');
      return;
    }
    try{
      const data = await WB.api.post("/api/cet6/translate", {
        text: info.text,
        kind: kindOf(info.text),
        context: {
          sentence: info.sentence,
          paper_id: infoPaper,
          section: sec.name,
          item: cur.title
        }
      });
      if(!data.translation && data.error){
        showPopover(info.rect,
          '<p class="status">' + U.escapeHtml(data.error) + "</p>" +
          '<div class="trans-actions"><button data-trans="close">关闭</button></div>');
        return;
      }
      const meaning = String(data.meaning || "");
      const phonetic = String(data.phonetic || "");
      const attr = function(value){
        return U.escapeHtml(String(value || "")).replace(/"/g, "&quot;");
      };
      const html = '<div class="trans-word">' + U.escapeHtml(info.text) + "</div>" +
        (phonetic ? '<div class="trans-phonetic">' + U.escapeHtml(phonetic) + "</div>" : "") +
        '<div class="trans-result">' + U.escapeHtml(data.translation || "") + "</div>" +
        (meaning && meaning !== data.translation
          ? '<p class="trans-meaning">' + U.escapeHtml(meaning) + "</p>" : "") +
        '<div class="trans-actions">' +
          '<button data-trans="vocab" data-word="' + attr(info.text) +
            '" data-meaning="' + attr(meaning || data.translation || "") +
            '" data-context="' + attr(info.sentence || "") + '">加入生词本</button>' +
          '<button data-trans="copy" data-text="' + attr(data.translation || "") + '">复制</button>' +
          '<button data-trans="close">关闭</button>' +
        "</div>";
      showPopover(info.rect, html);
      WB.noteAction("翻译：" + info.text);
    }catch(err){
      showPopover(info.rect,
        '<p class="status">翻译失败：' + U.escapeHtml(WB.api.errorText(err)) + "</p>" +
        '<div class="trans-actions"><button data-trans="close">关闭</button></div>');
    }
  }

  function currentTranslation(){
    const id = WB.paper.currentItemId();
    return WB.state.translation[id] || {};
  }

  function applyZh(){
    if(!WB.dom.sentences) return;
    const map = currentTranslation();
    WB.dom.sentences.querySelectorAll(".zh[data-zh]").forEach(function(node){
      const i = Number(node.dataset.zh);
      const item = map[String(i)] || map[i] || {};
      const text = String(item.translation || "");
      node.textContent = text;
      // 译文跟着原文走：原文藏起来时译文也藏着；原文一露，译文就在下面。
      const card = node.closest(".card");
      const enHidden = !!card && !!card.querySelector(".en.hidden");
      node.classList.toggle("hidden", !text || enHidden);
    });
  }

  // 自动补译文：换到某一段时在后台补缺失的句子，不再有「显示译文」按钮。
  // 失败 1 分钟后才重试，免得每次重渲染都打一次接口。
  const lastTry = {};
  let autoBusy = false;

  function missingRows(){
    const cur = WB.paper.currentItem();
    const map = currentTranslation();
    return cur ? cur.sentences.filter(function(s){
      const row = map[String(s.i)] || map[s.i];
      return !(row && row.translation);
    }) : [];
  }

  async function autoCurrent(){
    if(autoBusy) return;
    if(!WB.api || !WB.api.ready) return;      // file:// 离线：只显示已有缓存
    const cur = WB.paper.currentItem();
    const id = WB.paper.currentItemId();
    if(!cur || !id || !cur.sentences.length) return;
    if(!missingRows().length) return;
    if(lastTry[id] && Date.now() - lastTry[id] < 60000) return;
    lastTry[id] = Date.now();
    autoBusy = true;
    const sec = WB.paper.currentSection();
    WB.status("正在补本段译文…");
    try{
      const data = await WB.api.post("/api/cet6/translate-item", {
        paper_id: WB.session.paperDir || WB.session.paper.title,
        section: sec.name,
        item: cur.title,
        sentences: cur.sentences.map(function(s){ return {i:s.i, en:s.en}; })
      });
      const merged = Object.assign({}, WB.state.translation[id] || {});
      const items = (data && data.items) || {};
      Object.keys(items).forEach(function(k){
        if(items[k] && items[k].translation) merged[k] = items[k];
      });
      WB.state.translation[id] = merged;
      WB.store.saveState();
      if(WB.paper.currentItemId() === id) applyZh();
      const total = cur.sentences.length;
      const got = cur.sentences.filter(function(s){
        return merged[String(s.i)] && merged[String(s.i)].translation;
      }).length;
      WB.status(got >= total
        ? "本段译文已就位，点「显示原文」时一起看。"
        : "本段译文补了 " + got + " / " + total + " 句。");
    }catch(err){
      WB.status("译文没拉到：" + WB.api.errorText(err) + "（稍后会再试）");
    }finally{
      autoBusy = false;
    }
  }

  function init(){
    if(bound) return;
    bound = true;
    document.addEventListener("selectionchange", function(){
      setTimeout(updateSelectionButton, 0);
    });
    document.addEventListener("scroll", function(){
      if(WB.dom.selVocabBtn) WB.dom.selVocabBtn.classList.add("hidden");
      if(WB.dom.selTranslateBtn) WB.dom.selTranslateBtn.classList.add("hidden");
      if(WB.dom.selAskBtn) WB.dom.selAskBtn.classList.add("hidden");
    }, true);
    WB.dom.selTranslateBtn.addEventListener("mousedown", function(e){ e.preventDefault(); });
    WB.dom.selTranslateBtn.addEventListener("click", function(){
      translateSelection();
    });
    if(WB.dom.selAskBtn){
      WB.dom.selAskBtn.addEventListener("mousedown", function(e){ e.preventDefault(); });
      WB.dom.selAskBtn.addEventListener("click", function(){
        const info = currentSelection() || lastInfo;
        if(!info || !info.text) return;
        WB.dom.selAskBtn.classList.add("hidden");
        WB.dom.selVocabBtn.classList.add("hidden");
        WB.dom.selTranslateBtn.classList.add("hidden");
        if(WB.ask && WB.ask.openFor){
          WB.ask.openFor({
            text: info.text,
            sentence: info.i,
            prefill: "「" + info.text + "」在这里是什么意思？"
          });
        }
      });
    }
    WB.dom.translationPop.addEventListener("click", function(e){
      const btn = e.target.closest("button[data-trans]");
      if(!btn) return;
      const act = btn.dataset.trans;
      if(act === "close") hidePopover();
      else if(act === "vocab"){
        WB.vocab.addWord(btn.dataset.word, btn.dataset.meaning, btn.dataset.context);
        btn.textContent = "已加入";
        btn.disabled = true;
      }else if(act === "copy"){
        const text = btn.dataset.text || "";
        if(navigator.clipboard && navigator.clipboard.writeText){
          navigator.clipboard.writeText(text).then(function(){
            WB.status("译文已复制。");
          }).catch(function(){});
        }
      }
    });
    document.addEventListener("click", function(e){
      const pop = WB.dom.translationPop;
      if(!pop || pop.classList.contains("hidden")) return;
      if(pop.contains(e.target)) return;
      if(e.target === WB.dom.selTranslateBtn) return;
      hidePopover();
    });
  }

  WB.translate = {
    init: init,
    translateSelection: translateSelection,
    autoCurrent: autoCurrent,
    applyZh: applyZh
  };
})(window.WB = window.WB || {});
