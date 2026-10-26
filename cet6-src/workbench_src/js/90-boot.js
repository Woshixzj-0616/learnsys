// @requires: 00-core.js, 10-storage.js, 20-paper.js, 30-audio.js, 40-render.js, 50-actions.js, 60-insights.js, 70-vocab.js, 75-search.js, 80-shortcuts.js
// 启动层：只定义 WB.boot(ctx)，由 99-launcher.js 在试卷加载完成后调用。
(function(WB){
  "use strict";

  // 原文文本指纹：句号 + 英文全文 + 题型名。任何断句/删改都会变。
  // 译文缓存是按句号索引存的，文本一变就必须整卷清掉，否则中文对不上英文。
  function textSignature(paper){
    var h = 2166136261;
    function feed(str){
      str = String(str == null ? "" : str);
      for(var k = 0; k < str.length; k++){
        h ^= str.charCodeAt(k);
        h = Math.imul(h, 16777619);
      }
      h ^= 10;
      h = Math.imul(h, 16777619);
    }
    (paper.sections || []).forEach(function(sec){
      feed(sec.letter); feed(sec.name);
      (sec.items || []).forEach(function(it){
        feed(it.title);
        (it.sentences || []).forEach(function(s){
          feed(s.i); feed(s.en);
        });
      });
    });
    return (h >>> 0).toString(16);
  }

  function boot(ctx){
    if(WB.session.booted) return;
    if(!ctx || !ctx.paper){
      window.showLaunchError("未能加载试卷数据。请确认 试卷\\试卷索引.js 和对应试卷的 data.js 存在。");
      return;
    }
    if(!ctx.paper.sections){
      window.showLaunchError("data.js 里没有 sections，试卷数据可能已损坏。");
      return;
    }

    WB.session.booted = true;
    WB.cacheDom();

    const paper = ctx.paper;
    WB.session.paper = paper;
    WB.session.paperDir = ctx.paperDir || paper.title;
    WB.session.audioBase = ctx.audioBase || "";

    WB.store.setPaper(paper);
    WB.state = WB.store.loadState(paper);

    // 原文校对变了：旧译文是按旧句子缓存的，必须清掉，否则中文对不上英文。
    const fixInfo = paper.transcript_fixes;
    const fixSig = fixInfo
      ? String(fixInfo.checked_at || "") + ":" + String(fixInfo.count || 0) +
        ":" + String(fixInfo.revision || 1)
      : "";
    if(fixSig && WB.state.transcriptFixSig !== fixSig){
      WB.state.translation = {};
      WB.state.transcriptFixSig = fixSig;
      WB.store.saveState();
    }
    // 原文文本变了（重排断句、删假句、改词）：旧译文按句号缓存，必须整卷清掉。
    var textSig = textSignature(paper);
    if(WB.state.textSig !== textSig){
      WB.state.translation = {};
      WB.state.textSig = textSig;
      WB.store.saveState();
    }

    WB.store.setOnSaved(function(){
      WB.store.recordHistory(WB.paper.historyInfo(), false);
    });

    WB.audio.onTick = WB.render.miniPlayer;
    WB.audio.onWindowChange = WB.render.sentenceBar;
    WB.audio.onLoopStat = WB.render.loopStat;
    WB.audio.onRateChange = WB.render.rateButtons;
    WB.audio.init();
    WB.audio.loadRate();

    WB.actions.init();
    WB.insights.init();
    WB.ask.init();
    WB.translate.init();
    WB.vocab.init();
    WB.search.init();
    WB.shortcuts.init();
    WB.render.rateButtons();
    // 令牌是异步取的；先按本地缓存渲染，拿到令牌后再补拉后台最近一次分析。
    WB.api.init().then(function(){
      const afterAudit = function(){
        if(WB.insights && WB.insights.restoreLatest) WB.insights.restoreLatest();
        if(WB.vocab && WB.vocab.syncFromServer) WB.vocab.syncFromServer();
        if(WB.translate && WB.translate.autoCurrent) WB.translate.autoCurrent();
      };
      // 先做整卷审计/恢复，再拉分析和生词：审计期间 hydrating=true，
      // 4 个同步字段的写操作会被拦一下，避免拿空快照覆盖服务端。
      if(WB.cet6Sync && WB.cet6Sync.syncPaper){
        Promise.resolve(WB.cet6Sync.syncPaper())
          .catch(function(){ return null; })
          .then(afterAudit);
      }else{
        afterAudit();
      }
    });

    document.title = paper.title + " · 精听工作台";
    WB.dom.paperTitle.textContent = paper.title;
    const modeText = paper.mode === "llm"
      ? "模型判断 " + (paper.llm_model || "").replace(/\[[^\]]*\]$/, "")
      : "规则切分";
    const stats = paper.stats || {};
    const fixMeta = paper.transcript_fixes;
    const fixes = fixMeta ? Number(fixMeta.count) || 0 : null;
    WB.dom.paperMeta.textContent =
      modeText + " · " + (stats.items || 0) + " 段 / " + (stats.sentences || 0) + " 句" +
      " · " + WB.util.fmt(paper.duration) +
      (fixMeta ? " · 原文已校对" + (fixes ? " " + fixes + " 处" : "") : "");
    WB.dom.paperMeta.title = "生成时间 " + paper.created_at +
      (fixMeta ? "\n原文校对：" + (fixMeta.checked_at || "") : "");
    WB.dom.audio.src = WB.audio.url(paper.audio);

    WB.render.nav();
    if(paper.sections.length && paper.sections[0].items.length){
      const p = WB.state.pos;
      const ok = p && paper.sections[p.si] && paper.sections[p.si].items[p.ii];
      WB.actions.selectItem(ok ? p.si : 0, ok ? p.ii : 0);
      WB.store.recordHistory(WB.paper.historyInfo(), true);
    }else{
      WB.dom.itemHeader.innerHTML =
        "<h2>没有可用的题型单元</h2><p class='meta'>请查看 目录.md 里的识别提示。</p>";
    }
  }

  WB.boot = boot;
})(window.WB = window.WB || {});
