// @requires: none
// 核心层：命名空间、运行时默认状态、DOM 缓存与纯工具函数。
(function(WB){
  "use strict";

  WB.util = {
    escapeHtml: function(s){
      return String(s).replace(/[&<>"']/g, function(c){
        return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];
      });
    },
    safeName: function(s){
      return String(s).replace(/[\\/:*?"<>|]/g, "_").slice(0, 60);
    },
    fmt: function(sec){
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      return m + ":" + String(s).padStart(2, "0");
    },
    fmtPrecise: function(sec){
      const m = Math.floor(sec / 60);
      const s = (sec % 60).toFixed(1);
      return m + ":" + String(s).padStart(4, "0");
    },
    fmtMini: function(sec){
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      return m + ":" + String(s).padStart(2, "0");
    },
    clamp: function(v, lo, hi){
      return Math.max(lo, Math.min(hi, v));
    },
    round1: function(v){
      return Math.round(Number(v) * 10) / 10;
    },
    ago: function(ts){
      const d = Date.now() - ts;
      if(d < 60000) return "刚刚";
      if(d < 3600000) return Math.floor(d / 60000) + " 分钟前";
      if(d < 86400000) return Math.floor(d / 3600000) + " 小时前";
      if(d < 172800000) return "昨天";
      const t = new Date(ts);
      return (t.getMonth() + 1) + "-" + t.getDate();
    }
  };

  // 运行态：刷新即重建，不写入 localStorage。
  WB.session = {
    paper: null,
    paperDir: "",
    audioBase: "",
    currentSi: 0,
    currentIi: 0,
    activeSentence: -1,
    rangeStart: 0,
    rangeEnd: 0,
    repeatLeft: 0,
    activeLoopCfg: {on:false, times:1},
    ab: null,
    boundaryTimer: null,
    onlyUndone: false,
    onlyReview: false,
    playRate: 1,
    booted: false,
    // 分析面板：收起只是隐藏，结果仍在 state.analysis 里
    analysisHidden: false,
    analysisBusy: false,
    panelKey: "",
    // 整段/整篇播放跟随：按时间找当前句，自动高亮 + 滚动
    followActive: false,
    followScope: "item",      // item / section / paper
    followSectionSi: -1,
    followIndex: -1,
    followPaused: false,      // 用户手动滚动后暂停跟随
    // AI 助手 / 翻译
    askAbort: null,
    askStreaming: false,
    askTab: "chat",
    askSelection: null,       // {text, sentence, i}：点「问 AI」时先把现场留住
    askLoaded: false,
    recentActions: []
  };

  // 最近操作：给「直接问」的结构化上下文用，只存内存，不落盘。
  WB.noteAction = function(text){
    if(!text) return;
    const arr = WB.session.recentActions;
    arr.push({at: new Date().toISOString(), text: String(text).slice(0, 160)});
    if(arr.length > 12) arr.splice(0, arr.length - 12);
  };

  // 持久化学习状态，由 boot 从 storage 载入。
  WB.state = null;

  // P17.1 退休开关：唯一构建常量。11-04 凭 tools/cet6_dualwrite_report.py
  // 的报告决定是否改 true；改完必须重建工作台 HTML 并同步快照。
  WB.FLAGS = { retired: false };

  WB.dom = {};

  WB.cacheDom = function(){
    const id = function(x){ return document.getElementById(x); };
    WB.dom = {
      audio: id("player"),
      playPauseBtn: id("playPauseBtn"),
      playerSeek: id("playerSeek"),
      playerCur: id("playerCur"),
      playerDur: id("playerDur"),
      playerRateBadge: id("playerRateBadge"),
      sentences: id("sentences"),
      nav: id("nav"),
      questions: id("questions"),
      empty: id("empty"),
      itemHeader: id("itemHeader"),
      warnings: id("warnings"),
      sentenceBarText: id("sentenceBarText"),
      audioStatus: id("audioStatus"),
      progressText: id("progressText"),
      progressBar: id("progressBar"),
      analysisPanel: id("analysisPanel"),
      analysisBody: id("analysisBody"),
      analysisDot: id("analysisDot"),
      analysisEmpty: id("analysisEmpty"),
      askPanel: id("askPanel"),
      askBody: id("askBody"),
      askInput: id("askInput"),
      askSend: id("askSend"),
      askStop: id("askStop"),
      askNew: id("askNew"),
      askBtn: id("askBtn"),
      askClose: id("askClose"),
      askModel: id("askModel"),
      askTabs: id("askTabs"),
      askChatView: id("askChatView"),
      askAnalysisView: id("askAnalysisView"),
      askHistoryView: id("askHistoryView"),
      askHistorySearch: id("askHistorySearch"),
      askHistoryList: id("askHistoryList"),
      askSuggest: id("askSuggest"),
      aiAnalyzeItem: id("aiAnalyzeItem"),
      aiAnalyzePaper: id("aiAnalyzePaper"),
      selAskBtn: id("selAskBtn"),
      selTranslateBtn: id("selTranslateBtn"),
      translationPop: id("translationPop"),
      playItemBtn: id("playItem"),
      followResume: id("followResume"),
      statsPanel: id("statsPanel"),
      statsBody: id("statsBody"),
      vocabPanel: id("vocabPanel"),
      vocabBody: id("vocabBody"),
      paperTitle: id("paperTitle"),
      paperMeta: id("paperMeta"),
      paperSelect: id("paperSelect"),
      paperSearch: id("paperSearch"),
      paperIndexTime: id("paperIndexTime"),
      recentPanel: id("recentPanel"),
      recentBtn: id("recentBtn"),
      playQuestionsBtn: id("playQuestions"),
      sentenceSearch: id("sentenceSearch"),
      searchResults: id("searchResults"),
      selVocabBtn: id("selVocabBtn"),
      importFile: id("importFile")
    };
  };

  WB.status = function(text){
    if(WB.dom.audioStatus) WB.dom.audioStatus.textContent = text;
  };
})(window.WB = window.WB || {});
