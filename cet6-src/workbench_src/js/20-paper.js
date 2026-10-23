// @requires: 00-core.js, 10-storage.js
// 试卷模型层：当前 Section/题型、句子范围、逐句学习状态（完成/断点/笔记/起点/循环/A-B）。
(function(WB){
  "use strict";

  const U = WB.util;

  function paper(){ return WB.session.paper; }
  function state(){ return WB.state; }

  function currentSection(){
    return paper().sections[WB.session.currentSi];
  }

  function currentItem(){
    return currentSection().items[WB.session.currentIi];
  }

  function itemId(sec, item){
    return sec.letter + "-" + item.index;
  }

  function currentItemId(){
    return itemId(currentSection(), currentItem());
  }

  function mapOf(name){
    const id = currentItemId();
    const group = state()[name] || {};
    return group[id] || {};
  }

  function doneMap(){ return mapOf("done"); }
  function errorMap(){ return mapOf("errors"); }
  function startMap(){ return mapOf("starts"); }
  function noteMap(){ return mapOf("notes"); }
  function loopCfgMap(){ return mapOf("loopCfg"); }
  function loopStatMap(){ return mapOf("loopStats"); }
  function abMap(){ return mapOf("ab"); }

  function loopCfgFor(i){
    const c = loopCfgMap()[i] || {};
    return {on: !!c.on, times: Math.max(1, Number(c.times) || 1)};
  }

  function loopStatText(st){
    const loops = Number(st && st.loops) || 0;
    if(!loops) return "";
    return "已循环 " + loops + " 次 · 共播放 " + (Number(st.plays) || 0) + " 次";
  }

  // 结构补句用独立 i（如 1001）避免和旧句号冲突；display 只负责界面显示。
  function sentenceLabel(s){
    if(!s) return "";
    return s.display != null ? String(s.display) : String(s.i).padStart(2, "0");
  }

  function effectiveStart(s){
    const m = startMap();
    return (m[s.i] != null) ? m[s.i] : s.start;
  }

  function baseRange(s, idx){
    const item = currentItem();
    const next = item.sentences[idx + 1];
    const start = Math.max(0, effectiveStart(s) - 0.15);
    let end = next ? effectiveStart(next) - 0.02 : s.end + 0.3;
    if(end <= start) end = start + 1.5;
    return [start, end];
  }

  function findSentence(i){
    const item = currentItem();
    return item.sentences.find(function(s){ return s.i === i; }) || null;
  }

  function findIndex(i){
    const item = currentItem();
    return item.sentences.findIndex(function(s){ return s.i === i; });
  }

  function baseRangeByIndex(i){
    const idx = findIndex(i);
    if(idx < 0) return null;
    return baseRange(currentItem().sentences[idx], idx);
  }

  // 读取某句的 A-B，并按当前句范围夹取。
  function resolveAB(i){
    const raw = abMap()[i];
    const r = baseRangeByIndex(i);
    if(!raw || !r) return {a:null, b:null, mode:null};
    let a = null, b = null;
    if(raw.a != null) a = U.round1(U.clamp(Number(raw.a), r[0], Math.max(r[0], r[1] - 0.2)));
    if(raw.b != null) b = U.round1(U.clamp(Number(raw.b), r[0], r[1]));
    if(raw.a != null && raw.b != null){
      if(a != null && b != null && b > a + 0.2) return {a:a, b:b, mode:"ab"};
      return {a:null, b:null, mode:null}; // A-B 无效时按整句播放，保留数据供用户修正
    }
    if(a != null) return {a:a, b:null, mode:"a"};
    return {a:null, b:b, mode:null};
  }

  function abView(i){
    const raw = abMap()[i];
    if(!raw || (raw.a == null && raw.b == null)) return {text:"", invalid:false};
    const r = resolveAB(i);
    if(r.mode === "ab") {
      return {text:"A " + U.fmtPrecise(r.a) + " / B " + U.fmtPrecise(r.b), invalid:false};
    }
    if(raw.a != null && raw.b != null) {
      return {text:"A-B 无效（B 需晚于 A 0.2 秒）", invalid:true};
    }
    if(r.a != null) return {text:"A " + U.fmtPrecise(r.a) + " / B —", invalid:false};
    return {text:"A — / B " + U.fmtPrecise(r.b), invalid:false};
  }

  function totalSentences(){
    let n = 0;
    paper().sections.forEach(function(sec){
      sec.items.forEach(function(item){ n += item.sentences.length; });
    });
    return n;
  }

  function totalDone(){
    let n = 0;
    paper().sections.forEach(function(sec){
      sec.items.forEach(function(item){
        const d = state().done[itemId(sec, item)] || {};
        n += Object.keys(d).filter(function(k){ return d[k]; }).length;
      });
    });
    return n;
  }

  function historyInfo(){
    const sec = currentSection();
    const item = currentItem();
    return {
      dir: WB.session.paperDir || paper().title,
      title: paper().title,
      done: totalDone(),
      total: totalSentences(),
      posLabel: sec && item ? sec.name + " / " + item.title : ""
    };
  }

  function currentId(){
    return currentItemId();
  }

  function toggleDone(i){
    if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("标记完成")){
      const m = state().done[currentId()] || {};
      return !!m[i];
    }
    const id = currentId();
    state().done[id] = state().done[id] || {};
    const wasDone = !!state().done[id][i];
    if(wasDone) delete state().done[id][i];
    else state().done[id][i] = true;
    const today = new Date().toISOString().slice(0, 10);
    state().daily = state().daily || {};
    const n = state().daily[today] || 0;
    state().daily[today] = wasDone ? Math.max(0, n - 1) : n + 1;
    WB.store.saveState();
    return !wasDone;
  }

  function toggleError(i, t){
    if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("断点标签")){
      return ((state().errors[currentId()] || {})[i] || []).slice();
    }
    const id = currentId();
    state().errors[id] = state().errors[id] || {};
    const arr = state().errors[id][i] || [];
    const at = arr.indexOf(t);
    if(at >= 0) arr.splice(at, 1);
    else arr.push(t);
    if(arr.length) state().errors[id][i] = arr;
    else delete state().errors[id][i];
    WB.store.saveState();
    return arr;
  }

  function setNote(i, text){
    if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("笔记")) return;
    const id = currentId();
    state().notes[id] = state().notes[id] || {};
    if(String(text).trim()) state().notes[id][i] = text;
    else delete state().notes[id][i];
    if(!Object.keys(state().notes[id]).length) delete state().notes[id];
    WB.store.saveState();
  }

  function setStart(i, t){
    const id = currentId();
    state().starts[id] = state().starts[id] || {};
    state().starts[id][i] = U.round1(t);
    WB.store.saveState();
    return state().starts[id][i];
  }

  // 单句恢复自动起点：只删这一句的手动起点，其它句不动。
  function resetStart(i){
    const id = currentId();
    const map = state().starts[id];
    if(!map || map[i] == null) return false;
    delete map[i];
    if(!Object.keys(map).length) delete state().starts[id];
    WB.store.saveState();
    return true;
  }

  function resetStarts(){
    const id = currentId();
    if(!state().starts[id] || !Object.keys(state().starts[id]).length) return false;
    delete state().starts[id];
    WB.store.saveState();
    return true;
  }

  function setLoopCfg(i, patch){
    const id = currentId();
    state().loopCfg[id] = state().loopCfg[id] || {};
    const cur = state().loopCfg[id][i] || {};
    cur.on = (patch.on != null) ? !!patch.on : !!cur.on;
    cur.times = Math.max(1, Number(patch.times != null ? patch.times : cur.times) || 1);
    state().loopCfg[id][i] = cur;
    WB.store.saveState();
    return cur;
  }

  function bumpLoopStat(i, key){
    if(i == null || i < 0) return null;
    if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("循环统计")) return null;
    const id = currentId();
    state().loopStats[id] = state().loopStats[id] || {};
    const st = state().loopStats[id][i] || {plays:0, loops:0};
    st[key] = (Number(st[key]) || 0) + 1;
    if(key === "loops") st.plays = (Number(st.plays) || 0) + 1;
    state().loopStats[id][i] = st;
    WB.store.saveState();
    if(WB.cet6Sync && WB.cet6Sync.schedule) WB.cet6Sync.schedule();
    return st;
  }

  function setABPoint(i, which, t){
    const r = baseRangeByIndex(i);
    if(!r) return {ok:false, message:"找不到这一句。"};
    const id = currentId();
    const raw = (state().ab[id] && state().ab[id][i]) || {};
    let a = (raw.a != null) ? Number(raw.a) : null;
    let b = (raw.b != null) ? Number(raw.b) : null;
    if(which === "A"){
      a = U.round1(U.clamp(t, r[0], Math.max(r[0], r[1] - 0.2)));
      if(b != null && b <= a + 0.2) b = null;
    }else{
      const nb = U.round1(U.clamp(t, r[0], Math.max(r[0], r[1] - 0.1)));
      if(a != null && nb <= a + 0.2){
        return {ok:false, message:"B 点必须晚于 A 点 0.2 秒以上。"};
      }
      b = nb;
    }
    state().ab[id] = state().ab[id] || {};
    state().ab[id][i] = {a:a, b:b};
    WB.store.saveState();
    return {ok:true, message:""};
  }

  function clearAB(i){
    const id = currentId();
    if(!state().ab[id]) return;
    delete state().ab[id][i];
    if(!Object.keys(state().ab[id]).length) delete state().ab[id];
    WB.store.saveState();
  }

  WB.paper = {
    currentSection: currentSection,
    currentItem: currentItem,
    itemId: itemId,
    currentItemId: currentItemId,
    doneMap: doneMap,
    errorMap: errorMap,
    startMap: startMap,
    noteMap: noteMap,
    loopCfgMap: loopCfgMap,
    loopStatMap: loopStatMap,
    abMap: abMap,
    loopCfgFor: loopCfgFor,
    loopStatText: loopStatText,
    sentenceLabel: sentenceLabel,
    effectiveStart: effectiveStart,
    baseRange: baseRange,
    baseRangeByIndex: baseRangeByIndex,
    findSentence: findSentence,
    findIndex: findIndex,
    resolveAB: resolveAB,
    abView: abView,
    totalSentences: totalSentences,
    totalDone: totalDone,
    historyInfo: historyInfo,
    toggleDone: toggleDone,
    toggleError: toggleError,
    setNote: setNote,
    setStart: setStart,
    resetStart: resetStart,
    resetStarts: resetStarts,
    setLoopCfg: setLoopCfg,
    bumpLoopStat: bumpLoopStat,
    setABPoint: setABPoint,
    clearAB: clearAB
  };
})(window.WB = window.WB || {});
