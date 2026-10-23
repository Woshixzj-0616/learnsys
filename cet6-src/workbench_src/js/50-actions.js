// @requires: 00-core.js, 10-storage.js, 20-paper.js, 30-audio.js, 40-render.js
// 操作层：把用户操作翻译成对 paper / audio 的调用，并触发渲染。
(function(WB){
  "use strict";

  const U = WB.util;
  let bound = false;

  function S(){ return WB.session; }

  function selectItem(si, ii){
    WB.dom.audio.pause();
    WB.audio.stopBoundaryTimer();
    S().activeSentence = -1;
    S().rangeEnd = 0;
    S().ab = null;
    S().currentSi = si;
    S().currentIi = ii;
    S().analysisHidden = false;
    WB.state.pos = {si:si, ii:ii};
    WB.store.saveState();
    document.querySelectorAll(".nav-item").forEach(function(b){
      b.classList.toggle("on",
        Number(b.dataset.si) === si && Number(b.dataset.ii) === ii);
    });
    WB.render.item();
    WB.insights.restoreLatest();
    if(WB.translate && WB.translate.applyZh) WB.translate.applyZh();
    WB.render.sentenceBar();
  }

  function setCardText(card, btn){
    const en = card.querySelector(".en");
    const show = en.classList.contains("hidden");
    en.classList.toggle("hidden", !show);
    // 原文和译文一起露：没有单独的「显示译文」开关了
    const zh = card.querySelector(".zh");
    if(zh) zh.classList.toggle("hidden", !show || !zh.textContent.trim());
    btn.textContent = show ? "隐藏原文" : "显示原文";
    btn.classList.toggle("on", show);
    if(show && WB.translate && WB.translate.autoCurrent) WB.translate.autoCurrent();
  }

  function setABFromCard(i, which){
    if(i !== S().activeSentence){
      WB.audio.focusSentence(i);
      WB.status("已选中第 " + i + " 句；播放到短语位置后再点「设 A/设 B」。");
      return;
    }
    const res = WB.audio.setABPoint(i, which);
    if(!res.ok){
      WB.status(res.message);
      return;
    }
    WB.render.cardAB(i);
    const view = WB.paper.abView(i);
    WB.status("第 " + i + " 句：" + (view.text || "A-B 已更新") +
      (view.invalid ? "（A-B 未生效，请重新设置）" : ""));
  }

  function clearABFromCard(i){
    WB.audio.clearAB(i);
    WB.render.cardAB(i);
    WB.status("第 " + i + " 句的 A-B 已清除。");
  }

  function onCardClick(e){
    const btn = e.target.closest("button");
    if(!btn) return;
    const card = btn.closest(".card");
    if(!card) return;
    const i = Number(card.dataset.i);

    if(btn.dataset.act === "text") setCardText(card, btn);
    if(btn.dataset.act === "toggle") WB.audio.toggleSentence(i);
    if(btn.dataset.act === "ask"){
      const s = WB.paper.findSentence(i);
      if(WB.ask && WB.ask.openFor) WB.ask.openFor({
        sentence: i,
        text: s ? s.en : "",
        prefill: "这一句为什么听不出来？"
      });
    }
    if(btn.dataset.act === "start"){
      if(!WB.audio.hasSource()){
        alert("请先加载音频。");
        return;
      }
      const t = WB.paper.setStart(i, WB.audio.now());
      WB.audio.invalidateTimeline();
      WB.render.sentences();
      WB.audio.refreshActiveWindow();
      WB.status("已把第 " + i + " 句起点设为 " + U.fmtPrecise(t) +
        "；点句子前的 ▶ 验证。");
    }
    if(btn.dataset.act === "resetStart"){
      if(WB.paper.resetStart(i)){
        WB.audio.invalidateTimeline();
        WB.render.sentences();
        WB.audio.refreshActiveWindow();
        WB.status("已恢复第 " + i + " 句的自动起点。");
      }
    }
    if(btn.dataset.act === "done"){
      if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("标记完成")) return;
      const nowDone = WB.paper.toggleDone(i);
      WB.noteAction((nowDone ? "标记完成" : "取消完成") + "第 " + i + " 句");
      WB.render.sentences();
      WB.render.progress();
      WB.cet6Sync.schedule();
    }
    if(btn.dataset.err){
      if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("断点标签")) return;
      WB.paper.toggleError(i, btn.dataset.err);
      WB.noteAction("第 " + i + " 句断点：" + btn.dataset.err);
      WB.render.sentences();
      WB.cet6Sync.schedule();
    }
    if(btn.dataset.ab === "A" || btn.dataset.ab === "B"){
      setABFromCard(i, btn.dataset.ab);
    }
    if(btn.dataset.ab === "clear") clearABFromCard(i);
  }

  function onCardInput(e){
    if(e.target.matches(".mini-range")){
      WB.audio.seekFraction(Number(e.target.dataset.range), e.target.value);
      return;
    }
    const ta = e.target.closest("textarea[data-note]");
    if(!ta) return;
    if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("笔记")) return;
    WB.paper.setNote(Number(ta.dataset.note), ta.value);
    WB.cet6Sync.schedule();
  }

  function onCardChange(e){
    const onBox = e.target.closest("input[data-loop-on]");
    const timesSel = e.target.closest("select[data-loop-times]");
    if(!onBox && !timesSel) return;
    if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("循环设置")) return;
    const i = Number(onBox ? onBox.dataset.loopOn : timesSel.dataset.loopTimes);
    const patch = {};
    if(onBox) patch.on = onBox.checked;
    if(timesSel) patch.times = Number(timesSel.value) || 1;
    const cur = WB.paper.setLoopCfg(i, patch);
    if(onBox){
      const sel = onBox.closest(".card-loop").querySelector("select[data-loop-times]");
      if(sel) sel.disabled = cur.on;
    }
    WB.audio.applyLoopCfg(i);
    WB.noteAction("第 " + i + " 句循环设置：" +
      (cur.on ? "不限次数" : "连播 " + cur.times + " 次"));
    WB.cet6Sync.schedule();
    WB.status(cur.on
      ? "第 " + i + " 句：不限次数循环。"
      : "第 " + i + " 句：连播 " + cur.times + " 次后自动暂停。");
  }

  function jumpToSentence(i){
    WB.render.sentences();
    let card = WB.dom.sentences.querySelector('.card[data-i="' + i + '"]');
    if(!card){
      outer:
      for(let si = 0; si < S().paper.sections.length; si++){
        const sec = S().paper.sections[si];
        for(let ii = 0; ii < sec.items.length; ii++){
          if(sec.items[ii].sentences.some(function(s){ return s.i === i; })){
            selectItem(si, ii);
            break outer;
          }
        }
      }
      card = WB.dom.sentences.querySelector('.card[data-i="' + i + '"]');
    }
    if(card){
      card.scrollIntoView({behavior:"smooth", block:"center"});
      WB.audio.playSentence(i);
    }
  }

  // 整篇/整卷播放跨到下一个题型单元：只换视图，不暂停、不清空播放区间。
  function followSwitch(si, ii){
    if(S().currentSi === si && S().currentIi === ii) return;
    const sec = S().paper.sections[si];
    const item = sec && sec.items[ii];
    if(!item) return;
    S().currentSi = si;
    S().currentIi = ii;
    WB.state.pos = {si:si, ii:ii};
    WB.store.saveState();
    document.querySelectorAll(".nav-item").forEach(function(b){
      b.classList.toggle("on",
        Number(b.dataset.si) === si && Number(b.dataset.ii) === ii);
    });
    WB.render.item();
    WB.render.sentenceBar();
    WB.noteAction("跟随播放切到：" + sec.name + " / " + item.title);
  }

  function exportItemRecord(){
    const sec = WB.paper.currentSection();
    const cur = WB.paper.currentItem();
    const id = WB.paper.currentItemId();
    const errors = WB.state.errors[id] || {};
    const notes = WB.state.notes[id] || {};
    const lines = [
      "错因清单 · " + S().paper.title,
      sec.name + " / " + cur.title,
      "生成时间：" + new Date().toLocaleString("zh-CN"),
      ""
    ];
    cur.sentences.forEach(function(s){
      const tags = errors[s.i] || [];
      const note = (notes[s.i] || "").trim();
      if(tags.length || note){
        lines.push("第 " + s.i + " 句" + (tags.length ? " [" + tags.join("、") + "]" : ""));
        lines.push("  " + s.en);
        lines.push("  时间：" + U.fmtPrecise(s.start));
        if(note) lines.push("  我的原因：" + note);
        lines.push("");
      }
    });
    if(lines.length <= 4) lines.push("本段还没有标记任何断点。");
    const blob = new Blob([lines.join("\n")], {type:"text/plain;charset=utf-8"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "错因清单-" + U.safeName(S().paper.title) + "-" +
      U.safeName(sec.name) + "-" + U.safeName(cur.title) + ".txt";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function toggleDoneActive(){
    if(S().activeSentence < 0) return;
    const card = WB.dom.sentences.querySelector('.card[data-i="' + S().activeSentence + '"]');
    const btn = card && card.querySelector('[data-act="done"]');
    if(btn) btn.click();
  }

  function toggleTagActive(n){
    if(S().activeSentence < 0) return;
    const card = WB.dom.sentences.querySelector('.card[data-i="' + S().activeSentence + '"]');
    const btn = card && card.querySelector('[data-err="' + WB.render.TAGS[n] + '"]');
    if(btn) btn.click();
  }

  function toggleLoopActive(){
    let i = S().activeSentence;
    if(i < 0){
      const card = document.querySelector(".card");
      if(!card) return;
      i = Number(card.dataset.i);
    }
    const cfg = WB.paper.loopCfgFor(i);
    const cur = WB.paper.setLoopCfg(i, {on:!cfg.on});
    const box = document.querySelector('[data-loop-on="' + i + '"]');
    if(box) box.checked = cur.on;
    const sel = document.querySelector('select[data-loop-times="' + i + '"]');
    if(sel) sel.disabled = cur.on;
    WB.audio.applyLoopCfg(i);
    WB.noteAction("第 " + i + " 句" + (cur.on ? "开启循环" : "关闭循环"));
    WB.cet6Sync.schedule();
    WB.status(cur.on
      ? "第 " + i + " 句已开启循环；再按 L 关闭。"
      : "第 " + i + " 句已关闭循环。");
  }

  function init(){
    if(bound) return;
    bound = true;

    WB.dom.nav.addEventListener("click", function(e){
      const secBtn = e.target.closest("button[data-sec-play]");
      if(secBtn){
        const si = Number(secBtn.dataset.secPlay);
        const sec = S().paper.sections[si];
        if(!sec) return;
        const r = WB.ranges.sectionRange(sec);
        WB.audio.playRange(r.start, r.end, null, {kind:"section", si:si});
        WB.status("正在播放整个 " + sec.name + "（界面会跟着当前句滚动）");
        WB.noteAction("整篇播放：" + sec.name);
        return;
      }
      const b = e.target.closest("button.nav-item");
      if(!b) return;
      selectItem(Number(b.dataset.si), Number(b.dataset.ii));
    });

    WB.dom.sentences.addEventListener("click", onCardClick);
    WB.dom.sentences.addEventListener("input", onCardInput);
    WB.dom.sentences.addEventListener("change", onCardChange);

    WB.dom.questions.addEventListener("click", function(e){
      const btn = e.target.closest("button[data-q]");
      if(!btn) return;
      const cur = WB.paper.currentItem();
      const q = cur.question_items.find(function(x){ return x.i === Number(btn.dataset.q); });
      if(!q) return;
      WB.audio.playRange(Math.max(0, q.start - 0.1), q.end + 0.1, null, {kind:"questions"});
    });

    WB.audio.onFollowItem = followSwitch;

    document.getElementById("playQuestions").addEventListener("click", WB.audio.playQuestions);
    document.getElementById("playItem").addEventListener("click", WB.audio.playItem);
    document.getElementById("exportBtn").addEventListener("click", exportItemRecord);

    if(WB.dom.followResume){
      WB.dom.followResume.addEventListener("click", function(){
        WB.audio.setFollowPaused(false);
      });
    }

    // 用户主动滚轮/触摸滚动时，先暂停跟随，避免把页面硬拽回去。
    window.addEventListener("wheel", function(){
      if(S().followActive && !S().followPaused) WB.audio.setFollowPaused(true);
    }, {passive:true});
    window.addEventListener("touchmove", function(){
      if(S().followActive && !S().followPaused) WB.audio.setFollowPaused(true);
    }, {passive:true});

    document.querySelectorAll("[data-rate]").forEach(function(b){
      b.addEventListener("click", function(){
        WB.audio.setRate(Number(b.dataset.rate) || 1);
      });
    });
  }

  WB.actions = {
    init: init,
    selectItem: selectItem,
    jumpToSentence: jumpToSentence,
    followSwitch: followSwitch,
    toggleDoneActive: toggleDoneActive,
    toggleTagActive: toggleTagActive,
    toggleLoopActive: toggleLoopActive
  };
})(window.WB = window.WB || {});
