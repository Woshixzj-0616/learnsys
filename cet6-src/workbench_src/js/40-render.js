// @requires: 00-core.js, 10-storage.js, 20-paper.js, 30-audio.js
// 渲染层：只读状态并输出 DOM，不修改学习数据。
(function(WB){
  "use strict";

  const U = WB.util;
  const TAGS = ["生词","听不出","连读","句法","走神"];

  function nav(){
    const box = WB.dom.nav;
    box.innerHTML = "";
    WB.session.paper.sections.forEach(function(sec, si){
      const h = document.createElement("div");
      h.className = "nav-section";
      h.innerHTML = "<span>" + U.escapeHtml(sec.name) + "</span>" +
        '<button type="button" class="sec-play" data-sec-play="' + si +
        '" title="连续播放整个 Section">整篇</button>';
      box.appendChild(h);
      sec.items.forEach(function(item, ii){
        const b = document.createElement("button");
        b.className = "nav-item";
        b.textContent = item.title + " · " + item.sentences.length + " 句";
        b.dataset.si = String(si);
        b.dataset.ii = String(ii);
        box.appendChild(b);
      });
    });
  }

  function item(){
    const sec = WB.paper.currentSection();
    const cur = WB.paper.currentItem();
    const c = cur.content;
    const q = cur.questions;
    const reviewN = cur.sentences.filter(function(s){ return s.review; }).length;
    WB.dom.itemHeader.innerHTML =
      "<h2>" + U.escapeHtml(cur.title) + "</h2>" +
      '<p class="meta">' + U.escapeHtml(sec.name) +
      " · 正文 " + U.fmt(c.start) + "–" + U.fmt(c.end) +
      " · " + cur.sentences.length + " 句" +
      " · 题目 " + cur.question_items.length + " 题" +
      " · 待校对 " + reviewN + " 句</p>";

    warnings();
    sentences();
    questions();

    const hasQuestions = q.end > q.start + 0.5 && cur.question_items.length > 0;
    WB.dom.playQuestionsBtn.disabled = !hasQuestions;
    progress();
  }

  function warnings(){
    const box = WB.dom.warnings;
    const ws = WB.session.paper.warnings || [];
    if(!ws.length){ box.innerHTML = ""; return; }
    box.innerHTML = '<div class="warnings"><b>识别提示</b><ul>' +
      ws.map(function(w){ return "<li>" + U.escapeHtml(w) + "</li>"; }).join("") +
      "</ul></div>";
  }

  function cardLoopRow(s, lc, statText){
    const loopOn = !!lc.on;
    const repeatTimes = Math.max(1, Number(lc.times) || 1);
    return '<div class="card-loop">' +
      '<label title="勾选后本句不限次数循环，直到你暂停">' +
        '<input type="checkbox" name="loop-on-' + s.i + '" data-loop-on="' + s.i + '"' +
        (loopOn ? " checked" : "") + "> 循环</label>" +
      '<select name="loop-times-' + s.i + '" data-loop-times="' + s.i + '"' + (loopOn ? " disabled" : "") +
        ' title="本句连播几次后自动暂停；勾选「循环」时不限次数">' +
        [1,2,3,5].map(function(n){
          return '<option value="' + n + '"' +
            (repeatTimes === n ? " selected" : "") + ">连播 " + n + " 次</option>";
        }).join("") +
      "</select>" +
      '<span class="loop-stat" data-loop-stat="' + s.i + '">' +
        U.escapeHtml(statText) + "</span>" +
    "</div>";
  }

  function cardABRow(s){
    const raw = WB.paper.abMap()[s.i] || {};
    const hasAB = (raw.a != null || raw.b != null);
    const view = WB.paper.abView(s.i);
    return '<div class="card-ab">' +
      '<button data-ab="A" data-ab-i="' + s.i + '" ' +
        'title="选中本句并播放到短语开头，再点设 A">设 A</button>' +
      '<button data-ab="B" data-ab-i="' + s.i + '" ' +
        'title="继续播放到短语结尾，再点设 B">设 B</button>' +
      '<button data-ab="clear" data-ab-i="' + s.i + '"' +
        (hasAB ? "" : " disabled") + ">清除 A-B</button>" +
      '<span class="ab-badge' + (view.invalid ? " invalid" : "") +
        '" data-ab-badge="' + s.i + '">' + U.escapeHtml(view.text) + "</span>" +
    "</div>";
  }

  function sentences(){
    const cur = WB.paper.currentItem();
    const done = WB.paper.doneMap();
    const errors = WB.paper.errorMap();
    const starts = WB.paper.startMap();
    const notes = WB.paper.noteMap();
    const loopCfg = WB.paper.loopCfgMap();
    const loopStats = WB.paper.loopStatMap();
    const rows = [];

    cur.sentences.forEach(function(s, si){
      const isDone = !!done[s.i];
      const errs = errors[s.i] || [];
      const manual = starts[s.i] != null;
      const st = manual ? starts[s.i] : s.start;
      const note = notes[s.i] || "";
      const lc = loopCfg[s.i] || {};
      const range = WB.paper.baseRange(s, si);
      const reviewBadge = s.review
        ? '<span class="review" title="' +
            U.escapeHtml((s.review_reasons || []).join("、") || "自动标记") +
          '">待校对</span>'
        : "";
      rows.push(
        '<article class="card' + (isDone ? " done" : "") + '" data-i="' + s.i + '">' +
          '<div class="card-head">' +
            '<span class="num">' + U.escapeHtml(WB.paper.sentenceLabel(s)) + "</span>" +
            '<span class="time' + (manual ? " manual" : "") + '">' +
              U.fmtPrecise(st) + "–" + U.fmtPrecise(s.end) +
              (manual ? "（手动）" : "") +
            "</span>" +
            reviewBadge +
            '<span class="badge">' + (isDone ? "已完成" : "未完成") + "</span>" +
          "</div>" +
          '<p class="en hidden">' + U.escapeHtml(s.en) + "</p>" +
          '<div class="zh hidden" data-zh="' + s.i + '"></div>' +
          '<div class="mini">' +
            '<button class="mini-btn" data-act="toggle">▶</button>' +
            '<input class="mini-range" name="range-' + s.i + '" data-range="' + s.i + '" type="range" ' +
              'min="0" max="1000" value="0">' +
            '<span class="mini-time" data-cur="' + s.i + '">0:00 / ' +
              U.fmtMini(range[1] - range[0]) + "</span>" +
          "</div>" +
          cardLoopRow(s, lc, WB.paper.loopStatText(loopStats[s.i])) +
          cardABRow(s) +
          '<textarea class="note" name="note-' + s.i + '" data-note="' + s.i + '" ' +
            'placeholder="我的原因：比如语速太快 / 从句太长 / 这个词没反应过来…">' +
            U.escapeHtml(note) + "</textarea>" +
          '<div class="controls">' +
            '<button data-act="text">显示原文</button>' +
            '<button data-act="ask" title="带着这一句问 AI">问 AI</button>' +
            '<button data-act="start" title="先把音频播到这句开头，暂停，再点这里">设起点</button>' +
            (manual
              ? '<button data-act="resetStart" class="on" title="删除这一句的手动起点，恢复自动时间">恢复自动</button>'
              : "") +
            '<button data-act="done" class="' + (isDone ? "done" : "") + '">' +
              (isDone ? "取消完成" : "标记完成") + "</button>" +
          "</div>" +
          '<div class="errors"><span>断点：</span>' +
            TAGS.map(function(t){
              return '<button data-err="' + t + '" class="' +
                (errs.indexOf(t) >= 0 ? "on" : "") + '">' + t + "</button>";
            }).join("") +
          "</div>" +
        "</article>"
      );
    });

    WB.dom.sentences.innerHTML = rows.join("");
    if(WB.dom.empty) WB.dom.empty.style.display = "none";
    if(WB.session.activeSentence >= 0){
      const curCard = document.querySelector('.card[data-i="' + WB.session.activeSentence + '"]');
      if(curCard) curCard.classList.add("active");
    }
    if(WB.session.followActive && WB.session.followIndex >= 0){
      const followCard = document.querySelector('.card[data-i="' + WB.session.followIndex + '"]');
      if(followCard) followCard.classList.add("follow");
    }
    if(WB.translate && WB.translate.applyZh) WB.translate.applyZh();
    if(WB.translate && WB.translate.autoCurrent) WB.translate.autoCurrent();
    miniPlayer();
  }

  function questions(){
    const cur = WB.paper.currentItem();
    if(!cur.question_items.length){
      WB.dom.questions.innerHTML = '<p class="status">本段没有识别到题目文本。</p>';
      return;
    }
    WB.dom.questions.innerHTML = cur.question_items.map(function(q){
      return '<div class="q-row">' +
        '<div class="q-head">' +
          '<button data-q="' + q.i + '">播放</button>' +
          "<span>Q" + (q.number || q.i) + " · " + U.fmtPrecise(q.start) + "</span>" +
        "</div>" +
        "<p>" + U.escapeHtml(q.en || "（未识别到题目文本）") + "</p>" +
      "</div>";
    }).join("");
  }

  function progress(){
    const cur = WB.paper.currentItem();
    const done = WB.paper.doneMap();
    const itemTotal = cur.sentences.length;
    const itemDone = cur.sentences.filter(function(s){ return !!done[s.i]; }).length;
    WB.dom.progressText.textContent =
      "本段 " + itemDone + " / " + itemTotal +
      "（总 " + WB.paper.totalDone() + " / " + WB.paper.totalSentences() + "）";
    WB.dom.progressBar.style.width =
      itemTotal ? (itemDone / itemTotal * 100) + "%" : "0%";
  }

  function miniPlayer(){
    const cur = WB.paper.currentItem();
    if(!cur) return;
    document.querySelectorAll(".mini-range").forEach(function(r){
      const i = Number(r.dataset.range);
      const idx = WB.paper.findIndex(i);
      if(idx < 0) return;
      const s = cur.sentences[idx];
      const base = WB.paper.baseRange(s, idx);
      const curEl = document.querySelector('[data-cur="' + i + '"]');
      if(i === WB.session.activeSentence && WB.session.rangeEnd > WB.session.rangeStart){
        const len = WB.session.rangeEnd - WB.session.rangeStart;
        const p = U.clamp((WB.dom.audio.currentTime - WB.session.rangeStart) / len, 0, 1);
        r.value = String(Math.round(p * 1000));
        if(curEl){
          curEl.textContent =
            U.fmtMini(Math.max(0, WB.dom.audio.currentTime - WB.session.rangeStart)) +
            " / " + U.fmtMini(len);
        }
      }else{
        r.value = "0";
        if(curEl) curEl.textContent = "0:00 / " + U.fmtMini(base[1] - base[0]);
      }
    });
    document.querySelectorAll(".card").forEach(function(card){
      const i = Number(card.dataset.i);
      const btn = card.querySelector('[data-act="toggle"]');
      if(!btn) return;
      const playing = (i === WB.session.activeSentence && !WB.dom.audio.paused);
      btn.textContent = playing ? "❚❚" : "▶";
      btn.classList.toggle("on", playing);
    });
  }

  function sentenceBar(){
    const el = WB.dom.sentenceBarText;
    if(!el) return;
    if(WB.dom.followResume){
      WB.dom.followResume.classList.toggle("hidden", !WB.session.followPaused);
    }
    if(WB.session.followActive && WB.session.followIndex >= 0){
      const fs = WB.paper.findSentence(WB.session.followIndex);
      const fr = WB.paper.baseRangeByIndex(WB.session.followIndex);
      const label = fs ? WB.paper.sentenceLabel(fs)
        : String(WB.session.followIndex).padStart(2, "0");
      el.textContent = "正在播放第 " + label + " 句" +
        (fr ? " · " + U.fmtPrecise(fr[0] + 0.15) + "–" + U.fmtPrecise(fs ? fs.end : fr[1]) : "") +
        (WB.session.followPaused ? " · 跟随已暂停" : " · 自动跟随");
      return;
    }
    const i = WB.session.activeSentence;
    if(i < 0){
      el.textContent = "当前句：未选中（点 ▶ 或按 ↑ ↓）";
      return;
    }
    const s = WB.paper.findSentence(i);
    const r = WB.paper.baseRangeByIndex(i);
    if(s && r){
      el.textContent = "当前句 " + WB.paper.sentenceLabel(s) +
        " · " + U.fmtPrecise(r[0] + 0.15) + "–" + U.fmtPrecise(s.end);
    }
  }

  function loopStat(i, st){
    const el = document.querySelector('[data-loop-stat="' + i + '"]');
    if(el) el.textContent = WB.paper.loopStatText(st);
  }

  function cardAB(i){
    const badge = document.querySelector('[data-ab-badge="' + i + '"]');
    const view = WB.paper.abView(i);
    if(badge){
      badge.textContent = view.text;
      badge.classList.toggle("invalid", view.invalid);
    }
    const clearBtn = document.querySelector('[data-ab="clear"][data-ab-i="' + i + '"]');
    if(clearBtn){
      const raw = WB.paper.abMap()[i] || {};
      clearBtn.disabled = !(raw.a != null || raw.b != null);
    }
  }

  function rateButtons(){
    document.querySelectorAll("[data-rate]").forEach(function(b){
      b.classList.toggle("on", Math.abs(Number(b.dataset.rate) - WB.session.playRate) < 0.001);
    });
  }

  WB.render = {
    nav: nav,
    item: item,
    warnings: warnings,
    sentences: sentences,
    questions: questions,
    progress: progress,
    miniPlayer: miniPlayer,
    sentenceBar: sentenceBar,
    loopStat: loopStat,
    cardAB: cardAB,
    rateButtons: rateButtons,
    TAGS: TAGS
  };
})(window.WB = window.WB || {});
