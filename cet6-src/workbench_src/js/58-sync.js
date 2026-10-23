// @requires: 00-core.js, 04-mode.js, 10-storage.js, 20-paper.js, 55-api.js, 56-dualwrite.js
// 同步层：增量编辑走 /api/cet6/sync；打开试卷时做一次整卷审计
// （写前比对 → 写入 → 写后校验），结果进 cet6_dualwrite_runs。
(function(WB){
  "use strict";

  const LEGACY_SERVER = "http://127.0.0.1:8765";
  let timer = null;
  let failedPushes = 0;

  function paperId(){
    return WB.session.paperDir ||
      (WB.session.paper && WB.session.paper.title) || "";
  }

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
    failedPushes += 1;
    return false;
  }

  async function push(analysis){
    if(!WB.state || !WB.session.paper) return false;
    if(WB.cet6Mode && WB.cet6Mode.readOnly) return false;
    return send(build(analysis));
  }

  function renderAll(){
    try{
      if(WB.render && WB.render.sentences) WB.render.sentences();
      if(WB.render && WB.render.progress) WB.render.progress();
      if(WB.render && WB.render.nav) WB.render.nav();
    }catch(e){}
  }

  async function fetchServerState(){
    const data = await WB.api.get(
      "/api/cet6/state?paper_id=" + encodeURIComponent(paperId()));
    return WB.dualwrite.mapServerState(WB.session.paper, (data && data.items) || []);
  }

  // 服务端 → 本地：服务端优先（退休后），done/errors 仍取并集。
  async function hydrateServer(){
    const mapped = await fetchServerState();
    const changed = WB.dualwrite.mergeIntoState(WB.state, mapped, true);
    if(changed){
      WB.store.saveState();
      renderAll();
    }
    return mapped;
  }

  // 审计成功后，只补本地缺口（不覆盖用户现有值），避免服务端多出的行丢掉。
  async function adoptMissing(){
    try{
      const mapped = await fetchServerState();
      if(WB.dualwrite.mergeIntoState(WB.state, mapped, false)){
        WB.store.saveState();
        renderAll();
      }
    }catch(e){}
  }

  function payloadFor(items, hydration, skipped){
    return {
      paper: WB.session.paper.title,
      paper_id: paperId(),
      items: items,
      hydration: hydration,
      mode: (WB.cet6Mode && WB.cet6Mode.HTTP) ? "http" : "file",
      paper_sig: WB.dualwrite.paperSig(WB.session.paper),
      client_ts: new Date().toISOString(),
      client_day: WB.dualwrite.clientDay(),
      push_failed: failedPushes,
      skipped_items: skipped || []
    };
  }

  // 打开试卷时的一次整卷审计。force=true 可重跑（例如 409 恢复后）。
  let syncedPaper = "";
  async function syncPaper(force){
    if(!WB.state || !WB.session.paper) return false;
    if(!WB.api || !WB.api.ready) return false;
    if(WB.cet6Mode && WB.cet6Mode.readOnly) return false;
    if(!force && syncedPaper === paperId()) return false;
    syncedPaper = paperId();
    if(WB.cet6Mode) WB.cet6Mode.hydrating = true;
    try{
      // 第一次用打开时的本地快照，先留证据：不先合并服务端，否则差异会被掩盖。
      const built = WB.dualwrite.canonicalRows(WB.session.paper, WB.state, []);
      try{
        const res = await WB.api.post(
          "/api/cet6/sync-paper", payloadFor(built.items, "local", []));
        failedPushes = 0;
        await adoptMissing();
        return !!res;
      }catch(err){
        if(!err || err.status !== 409) throw err;
        // 本地为空 / 服务端有进度：先从服务端恢复，再带 hydration=state 重试一次。
        const mapped = await hydrateServer();
        const built2 = WB.dualwrite.canonicalRows(
          WB.session.paper, WB.state, mapped.skipped);
        const res2 = await WB.api.post(
          "/api/cet6/sync-paper", payloadFor(built2.items, "state", mapped.skipped));
        failedPushes = 0;
        return !!res2;
      }
    }catch(e){
      // 审计失败不拦使用；下次打开会重试。
      return false;
    }finally{
      if(WB.cet6Mode) WB.cet6Mode.hydrating = false;
    }
  }

  function schedule(){
    if(WB.cet6Mode && WB.cet6Mode.readOnly) return;
    if(timer) clearTimeout(timer);
    timer = setTimeout(function(){
      timer = null;
      push(null);
    }, 1200);
  }

  // 关窗/切后台时把防抖中的最后一笔推掉，避免下次打开审计出现缺口。
  function flush(){
    if(!timer) return;
    clearTimeout(timer);
    timer = null;
    push(null);
  }
  window.addEventListener("pagehide", flush);
  document.addEventListener("visibilitychange", function(){
    if(document.visibilityState === "hidden") flush();
  });

  WB.cet6Sync = {build: build, buildFor: buildFor, push: push, schedule: schedule,
                 syncPaper: syncPaper, flush: flush};
})(window.WB = window.WB || {});
