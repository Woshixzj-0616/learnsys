// @requires: 00-core.js, 10-storage.js, 20-paper.js, 55-api.js
// 同步层：把当前段的逐句进度（标签/笔记/循环/完成）送到学习后台。
// 断点同步按 dedupe_key 去重；这里只负责「拼快照 + 防抖」，不碰渲染。
(function(WB){
  "use strict";

  const LEGACY_SERVER = "http://127.0.0.1:8765";
  let timer = null;

  function buildFor(sec, cur, analysis){
    const id = WB.paper.itemId(sec, cur);
    const errors = WB.state.errors[id] || {};
    const notes = WB.state.notes[id] || {};
    const stats = WB.state.loopStats[id] || {};
    const doneMap = WB.state.done[id] || {};
    const done = [];
    const sentences = cur.sentences.map(function(s){
      if(doneMap[s.i]) done.push(s.i);
      const st = stats[s.i] || {};
      return {
        sentence: s.i,
        en: s.en,
        tags: errors[s.i] || [],
        note: notes[s.i] || "",
        loops: Number(st.loops) || 0,
        plays: Number(st.plays) || 0
      };
    });
    return {
      paper: WB.session.paper.title,
      paper_id: WB.session.paperDir || WB.session.paper.title,
      section: sec.name,
      item: cur.title,
      sentences: sentences,
      done: done,
      analysis: analysis || null
    };
  }

  function build(analysis){
    return buildFor(WB.paper.currentSection(), WB.paper.currentItem(), analysis);
  }

  async function send(payload){
    try{
      if(WB.api && WB.api.ready){
        await WB.api.post("/api/cet6/sync", payload);
        return true;
      }
      if(location.protocol === "file:"){
        const res = await fetch(LEGACY_SERVER + "/api/cet6/sync", {
          method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify(payload)
        });
        return res.ok;
      }
    }catch(e){
      // 后台没开 / 端口变了：工作台照常用，下次改动会再试
    }
    return false;
  }

  async function push(analysis){
    if(!WB.state || !WB.session.paper) return false;
    return send(build(analysis));
  }

  // 打开试卷时把整卷各段的进度补一遍：之前后台没开时点的「完成」也能进学习工作台。
  // 每份试卷每次打开只跑一遍，失败不拦使用。
  let syncedPaper = "";
  async function syncPaper(){
    if(!WB.state || !WB.session.paper) return false;
    if(!WB.api || !WB.api.ready) return false;
    const key = WB.session.paperDir || WB.session.paper.title;
    if(!key || syncedPaper === key) return false;
    syncedPaper = key;
    const ok = [];
    const sections = (WB.session.paper.sections || []);
    for(let i = 0; i < sections.length; i++){
      const sec = sections[i];
      const items = sec.items || [];
      for(let j = 0; j < items.length; j++){
        try{
          ok.push(await send(buildFor(sec, items[j], null)));
        }catch(e){
          ok.push(false);
        }
      }
    }
    return ok.every(Boolean);
  }

  function schedule(){
    if(timer) clearTimeout(timer);
    timer = setTimeout(function(){
      timer = null;
      push(null);
    }, 1200);
  }

  WB.cet6Sync = {build: build, buildFor: buildFor, push: push, schedule: schedule,
                 syncPaper: syncPaper};
})(window.WB = window.WB || {});
