// @requires: 00-core.js, 20-paper.js, 30-audio.js, 55-api.js
// 句子内听写：不再有独立专项队列，精听里想练哪句就点哪句。
// 提交后按内容词算分，漏听词高亮并自动收进英语复习。
(function(WB){
  "use strict";

  const U = WB.util;

  function paperId(){
    // 与进度同步同一口径：进度表的 paper_id 是目录名或标题，不带 data.js 的 _时长 后缀。
    if(WB.cet6Sync && WB.cet6Sync.paperId) return WB.cet6Sync.paperId();
    return WB.session.paperDir ||
      (WB.session.paper && WB.session.paper.title) || "";
  }

  function toggle(card, i){
    const old = card.querySelector(".dictation-box");
    if(old){ old.remove(); return; }
    const s = WB.paper.findSentence(i);
    if(!s) return;
    const box = document.createElement("div");
    box.className = "dictation-box";
    box.dataset.sentence = String(i);
    box.innerHTML =
      '<div class="dictation-head"><b>听写这一句</b>' +
      '<button type="button" data-dictation-play>再播一遍</button>' +
      '<span class="dictation-status"></span></div>' +
      '<textarea class="dictation-input" id="dictation-input-' + i + '" name="dictation-' + i + '" rows="3" ' +
      'placeholder="听到什么写什么，不用管大小写和标点；Ctrl+Enter 提交"></textarea>' +
      '<div class="dictation-actions">' +
      '<button type="button" data-dictation-submit>提交</button>' +
      '<button type="button" data-dictation-cancel>收起</button></div>';
    card.appendChild(box);
    const input = box.querySelector(".dictation-input");
    box._startedAt = Date.now();
    input.focus();
    box.querySelector("[data-dictation-play]").addEventListener("click", function(){
      WB.audio.playSentence(i);
    });
    box.querySelector("[data-dictation-cancel]").addEventListener("click", function(){
      box.remove();
    });
    box.querySelector("[data-dictation-submit]").addEventListener("click", function(){
      submit(box, s);
    });
    input.addEventListener("keydown", function(e){
      if((e.ctrlKey || e.metaKey) && e.key === "Enter") submit(box, s);
    });
  }

  async function submit(box, s){
    const input = box.querySelector(".dictation-input");
    const status = box.querySelector(".dictation-status");
    const answer = String(input.value || "").trim();
    if(!answer){ status.textContent = "先写点什么再提交。"; return; }
    const sec = WB.paper.currentSection();
    const item = WB.paper.currentItem();
    const body = {
      paper_id: paperId(),
      section: sec.name,
      item: item.title,
      sentence: s.i,
      answer: answer,
      duration_s: Math.max(0, Math.round((Date.now() - box._startedAt) / 1000))
    };
    status.textContent = "提交中…";
    try{
      const data = await WB.api.post("/api/cet6/drill/attempt", body);
      renderResult(box, s, data);
      WB.status("听写已提交：" + data.content_matched + " / " +
        data.content_total + " 个内容词。");
    }catch(e){
      status.textContent = e.message || "提交失败";
    }
  }

  function renderResult(box, s, data){
    const pct = data.content_total
      ? Math.round(data.content_matched * 100 / data.content_total) : 0;
    const parts = (data.parts || []).map(function(part){
      return part.miss
        ? '<mark class="dictation-miss">' + U.escapeHtml(part.text) + "</mark>"
        : U.escapeHtml(part.text);
    }).join("");
    box.innerHTML =
      '<div class="dictation-head"><b>听写结果</b>' +
      '<span class="dictation-score">' + pct + "% · 内容词 " +
      data.content_matched + " / " + data.content_total + "</span></div>" +
      '<p class="dictation-expected">' + parts + "</p>" +
      (data.cards_created
        ? '<p class="dictation-cards">漏听词已收进英语复习：' + data.cards_created + " 张卡</p>"
        : '<p class="dictation-cards">这句没有新的漏听词。</p>') +
      '<div class="dictation-actions">' +
      '<button type="button" data-dictation-retry>再听写一次</button>' +
      '<button type="button" data-dictation-close>收起</button></div>';
    box.querySelector("[data-dictation-retry]").addEventListener("click", function(){
      const card = box.parentElement;
      box.remove();
      toggle(card, s.i);
    });
    box.querySelector("[data-dictation-close]").addEventListener("click", function(){
      box.remove();
    });
  }

  WB.dictation = { toggle: toggle };
})(WB);
