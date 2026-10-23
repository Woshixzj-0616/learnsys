// @requires: 00-core.js
// 数据层：所有 localStorage 键的唯一来源，负责学习状态、历史、最近、生词与导出。
(function(WB){
  "use strict";

  const KEYS = {
    statePrefix: "listening_splitter_v1_",
    rate: "listening_workbench_rate_v1",
    vocab: "listening_workbench_vocab_v1",
    history: "listening_workbench_history_v1",
    last: "listening_workbench_last_paper_v1",
    ai: "listening_workbench_ai_v1"
  };
  const HISTORY_MAX = 12;

  let currentKey = "";
  let lastTouchAt = 0;
  let onSaved = null;

  function obj(v){
    return (v && typeof v === "object" && !Array.isArray(v)) ? v : {};
  }

  function stateKey(paper){
    return KEYS.statePrefix + ((paper && (paper.paper_id || paper.title)) || "unknown");
  }

  function emptyState(){
    return {
      done:{}, errors:{}, starts:{}, notes:{}, analysis:{}, daily:{},
      pos:null, loopCfg:{}, loopStats:{}, ab:{}, translation:{},
      cet6ConversationId:0, transcriptFixSig:""
    };
  }

  function sanitizeState(s){
    const out = emptyState();
    out.done = obj(s.done);
    out.errors = obj(s.errors);
    out.starts = obj(s.starts);
    out.notes = obj(s.notes);
    out.analysis = obj(s.analysis);
    out.daily = obj(s.daily);
    out.pos = s.pos || null;
    out.loopCfg = obj(s.loopCfg);
    out.loopStats = obj(s.loopStats);
    out.ab = obj(s.ab);
    out.translation = obj(s.translation);
    out.cet6ConversationId = Number(s.cet6ConversationId) || 0;
    out.transcriptFixSig = String(s.transcriptFixSig || "");
    Object.keys(out.ab).forEach(function(id){
      const m = out.ab[id];
      if(!m || typeof m !== "object" || Array.isArray(m)){ delete out.ab[id]; return; }
      Object.keys(m).forEach(function(si){
        const v = m[si];
        if(!v || typeof v !== "object" || Array.isArray(v)) delete m[si];
      });
    });
    return out;
  }

  function setPaper(paper){
    currentKey = stateKey(paper);
    lastTouchAt = 0;
  }

  function loadState(paper){
    try{
      const raw = localStorage.getItem(stateKey(paper));
      if(!raw) return emptyState();
      return sanitizeState(JSON.parse(raw));
    }catch(e){
      return emptyState();
    }
  }

  function saveState(){
    if(!currentKey || !WB.state) return;
    try{
      localStorage.setItem(currentKey, JSON.stringify(WB.state));
    }catch(e){}
    if(onSaved) onSaved();
  }

  function setOnSaved(fn){
    onSaved = typeof fn === "function" ? fn : null;
  }

  function paperDoneCount(paper){
    try{
      const raw = localStorage.getItem(stateKey(paper));
      if(!raw) return 0;
      const st = JSON.parse(raw);
      const done = obj(st.done);
      let n = 0;
      Object.keys(done).forEach(function(k){
        const d = obj(done[k]);
        Object.keys(d).forEach(function(s){ if(d[s]) n += 1; });
      });
      return n;
    }catch(e){ return 0; }
  }

  function loadRate(){
    try{
      const r = Number(localStorage.getItem(KEYS.rate));
      return r > 0 ? r : 1;
    }catch(e){ return 1; }
  }

  function saveRate(r){
    try{ localStorage.setItem(KEYS.rate, String(r)); }catch(e){}
  }

  function loadVocab(){
    try{
      const a = JSON.parse(localStorage.getItem(KEYS.vocab) || "[]");
      return Array.isArray(a) ? a : [];
    }catch(e){ return []; }
  }

  function saveVocab(arr){
    if(WB.cet6Mode && WB.cet6Mode.readOnly) return;
    try{ localStorage.setItem(KEYS.vocab, JSON.stringify(arr)); }catch(e){}
  }

  // AI 助手的全局当前会话：跨试卷共用一段对话，历史列表仍按服务端 module=cet6 取。
  function loadAi(){
    try{
      const raw = JSON.parse(localStorage.getItem(KEYS.ai) || "{}");
      const top = Number(raw.fabTop);
      return {
        conversationId: Number(raw.conversationId) || 0,
        fabTop: isFinite(top) && top >= 0 ? top : null
      };
    }catch(e){ return {conversationId: 0, fabTop: null}; }
  }

  function saveAi(obj){
    try{
      const cur = loadAi();
      const next = Object.assign({}, cur, obj || {});
      localStorage.setItem(KEYS.ai, JSON.stringify(next));
    }catch(e){}
  }

  function getLast(){
    try{ return localStorage.getItem(KEYS.last) || ""; }catch(e){ return ""; }
  }

  function setLast(dir){
    try{ localStorage.setItem(KEYS.last, dir); }catch(e){}
  }

  function readHistory(){
    try{
      const a = JSON.parse(localStorage.getItem(KEYS.history) || "[]");
      return Array.isArray(a) ? a : [];
    }catch(e){ return []; }
  }

  function writeHistory(arr){
    try{
      localStorage.setItem(KEYS.history, JSON.stringify(arr.slice(0, HISTORY_MAX)));
    }catch(e){}
  }

  // 把当前试卷进度写进「最近」；默认 2 秒节流，force=true 立即写。
  function recordHistory(info, force){
    if(!info || !info.dir) return;
    const now = Date.now();
    if(!force && now - lastTouchAt < 2000) return;
    lastTouchAt = now;
    const arr = readHistory().filter(function(x){ return x.dir !== info.dir; });
    arr.unshift({
      dir: info.dir,
      title: info.title || info.dir,
      at: now,
      done: info.done || 0,
      total: info.total || 0,
      posLabel: info.posLabel || ""
    });
    writeHistory(arr);
  }

  function collectAllData(){
    const store = {};
    for(let i = 0; i < localStorage.length; i++){
      const k = localStorage.key(i);
      if(k && k.indexOf("listening_") === 0){
        store[k] = localStorage.getItem(k);
      }
    }
    return {version: 1, exportedAt: new Date().toISOString(), store: store};
  }

  function importData(data){
    if(WB.cet6Mode && WB.cet6Mode.readOnly){
      throw new Error("只读模式：请从学习工作台打开后再导入数据");
    }
    if(!data || !data.store || typeof data.store !== "object"){
      throw new Error("不是本工作台导出的数据文件");
    }
    const keys = Object.keys(data.store);
    if(!keys.length) throw new Error("文件里没有学习数据");
    keys.forEach(function(k){ localStorage.setItem(k, data.store[k]); });
    return keys.length;
  }

  WB.store = {
    KEYS: KEYS,
    stateKey: stateKey,
    setPaper: setPaper,
    loadState: loadState,
    saveState: saveState,
    setOnSaved: setOnSaved,
    paperDoneCount: paperDoneCount,
    loadRate: loadRate,
    saveRate: saveRate,
    loadVocab: loadVocab,
    saveVocab: saveVocab,
    loadAi: loadAi,
    saveAi: saveAi,
    getLast: getLast,
    setLast: setLast,
    readHistory: readHistory,
    writeHistory: writeHistory,
    recordHistory: recordHistory,
    collectAllData: collectAllData,
    importData: importData
  };
})(window.WB = window.WB || {});
