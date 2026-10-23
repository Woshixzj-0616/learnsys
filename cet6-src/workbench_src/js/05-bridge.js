// @requires: 00-core.js, 04-mode.js
// 迁移桥：旧 file:// 工作台 → 学习系统后台；HTTP 首开 → 从后台恢复。
// 退休后（WB.FLAGS.retired=true）file:// 只读，不再推送；HTTP 的恢复交给 90-boot/58-sync。
// 只碰 localStorage 与网络，不参与渲染；放在 10-storage 之前，保证恢复/导入
// 在试卷层读取状态之前就已经安排好（HTTP 恢复会 reload 一次）。
(function(WB){
  "use strict";

  const PREFIX = "listening_";
  const STATE_PREFIX = "listening_splitter_v1_";
  const LEARNING_KEYS = [
    "listening_workbench_vocab_v1",
    "listening_workbench_history_v1"
  ];
  const MARK_IMPORTED = "listening_bridge_imported_v1";
  const MARK_BACKUP = "listening_bridge_backup_v1";
  const MARK_RESTORED = "listening_bridge_restored_v1";
  const REDIRECT_GUARD = "listening_bridge_redirect_v1";
  const SERVER = "http://127.0.0.1:8765";
  const SERVERS = [SERVER, "http://127.0.0.1:8766"];

  function isFile(){ return location.protocol === "file:"; }
  function isHttp(){ return location.protocol === "http:" || location.protocol === "https:"; }

  function collectAll(){
    const store = {};
    for(let i = 0; i < localStorage.length; i++){
      const k = localStorage.key(i);
      if(!k || k.indexOf(PREFIX) !== 0) continue;
      if(k === MARK_IMPORTED || k === MARK_RESTORED || k === MARK_BACKUP) continue;
      store[k] = localStorage.getItem(k);
    }
    return store;
  }

  function hasLearningData(){
    for(let i = 0; i < localStorage.length; i++){
      const k = localStorage.key(i) || "";
      const v = localStorage.getItem(k);
      if(!v) continue;
      if(k.indexOf(STATE_PREFIX) === 0 && v !== "{}" && v !== "null") return true;
      if(LEARNING_KEYS.indexOf(k) >= 0 && v !== "[]") return true;
    }
    return false;
  }

  function backup(store){
    try{
      const payload = {
        version: 1,
        exportedAt: new Date().toISOString(),
        note: "六级精听迁移到学习系统前的自动备份；可在工作台「导入数据」恢复。",
        store: store
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)],
        {type: "application/json;charset=utf-8"});
      const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "六级精听-迁移备份-" + stamp + ".json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function(){ URL.revokeObjectURL(a.href); }, 1000);
      return true;
    }catch(e){
      console.warn("六级迁移备份下载失败：", e);
      return false;
    }
  }

  function ensureBackup(store){
    if(localStorage.getItem(MARK_BACKUP)) return;
    if(backup(store)){
      try{ localStorage.setItem(MARK_BACKUP, new Date().toISOString()); }catch(e){}
    }
  }

  async function importFileData(store, base){
    const server = base || SERVER;
    const keys = Object.keys(store);
    if(!keys.length){
      try{ localStorage.setItem(MARK_IMPORTED, new Date().toISOString()); }catch(e){}
      return;
    }
    ensureBackup(store);              // 迁移前先留一份可「导入数据」恢复的 JSON
    try{
      const res = await fetch(server + "/api/cet6/import", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({items: store})
      });
      if(!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      try{ localStorage.setItem(MARK_IMPORTED, new Date().toISOString()); }catch(e){}
      console.info("六级进度已迁移到学习系统：" + (data.count || 0) + " 项");
    }catch(e){
      // 服务没开 / 端口变了：不写标记，下次打开 file:// 工作台会重试
      console.warn("六级进度迁移失败（下次打开会重试）：", e);
    }
  }

  // ---- 合并两份进度（file:// 推上来的 与 当前浏览器里的）----
  // 规则：done/标签取并集；笔记/分析/位置以本地为准，本地没有才用后台；统计取大。
  // 只有后台那份「上次合并后变过」才重新合并（用指纹判断），避免每次刷新都把
  // 「取消完成」的句子又翻出来。
  const MERGE_SIG_KEY = "learnsys_cet6_merge_sig_v1";

  function union(a, b){
    const out = [];
    (Array.isArray(a) ? a : []).forEach(function(x){ if(out.indexOf(x) < 0) out.push(x); });
    (Array.isArray(b) ? b : []).forEach(function(x){ if(out.indexOf(x) < 0) out.push(x); });
    return out;
  }

  function mergeState(localRaw, serverRaw){
    let L, S;
    try{ L = JSON.parse(localRaw); }catch(e){ return serverRaw; }
    try{ S = JSON.parse(serverRaw); }catch(e){ return localRaw; }
    if(!L || typeof L !== "object" || Array.isArray(L)) return serverRaw;
    if(!S || typeof S !== "object" || Array.isArray(S)) return localRaw;
    const out = JSON.parse(JSON.stringify(L));
    out.done = out.done || {};
    Object.keys(S.done || {}).forEach(function(item){
      const src = S.done[item] || {};
      const dst = out.done[item] || (out.done[item] = {});
      Object.keys(src).forEach(function(s){ if(src[s]) dst[s] = true; });
    });
    out.errors = out.errors || {};
    Object.keys(S.errors || {}).forEach(function(item){
      const src = S.errors[item] || {};
      const dst = out.errors[item] || (out.errors[item] = {});
      Object.keys(src).forEach(function(s){ dst[s] = union(dst[s], src[s]); });
    });
    function fillMissing(dst, src){
      Object.keys(src || {}).forEach(function(item){
        if(dst[item] == null){ dst[item] = src[item]; return; }
        const a = dst[item], b = src[item];
        if(!a || typeof a !== "object" || Array.isArray(a)) return;
        if(!b || typeof b !== "object" || Array.isArray(b)) return;
        Object.keys(b).forEach(function(s){
          if(a[s] == null) a[s] = b[s];
        });
      });
    }
    ["notes", "starts", "ab", "loopCfg"].forEach(function(f){
      out[f] = out[f] || {};
      fillMissing(out[f], S[f]);
    });
    out.analysis = out.analysis || {};
    Object.keys(S.analysis || {}).forEach(function(item){
      if(out.analysis[item] == null) out.analysis[item] = S.analysis[item];
    });
    out.loopStats = out.loopStats || {};
    Object.keys(S.loopStats || {}).forEach(function(item){
      const src = S.loopStats[item] || {};
      const dst = out.loopStats[item] || (out.loopStats[item] = {});
      Object.keys(src).forEach(function(s){
        const a = dst[s] || {}, b = src[s] || {};
        dst[s] = {plays: Math.max(Number(a.plays) || 0, Number(b.plays) || 0),
                  loops: Math.max(Number(a.loops) || 0, Number(b.loops) || 0)};
      });
    });
    out.translation = out.translation || {};
    Object.keys(S.translation || {}).forEach(function(item){
      const src = S.translation[item] || {};
      const dst = out.translation[item] || (out.translation[item] = {});
      Object.keys(src).forEach(function(s){
        const a = dst[s] || {}, b = src[s] || {};
        if(!a.translation && b.translation) dst[s] = b;
      });
    });
    out.daily = out.daily || {};
    Object.keys(S.daily || {}).forEach(function(day){
      out.daily[day] = Math.max(Number(out.daily[day]) || 0, Number(S.daily[day]) || 0);
    });
    if(!out.pos && S.pos) out.pos = S.pos;
    out.cet6ConversationId = Math.max(Number(out.cet6ConversationId) || 0,
                                      Number(S.cet6ConversationId) || 0);
    return JSON.stringify(out);
  }

  function mergeVocab(localRaw, serverRaw){
    let L, S;
    try{ L = JSON.parse(localRaw); }catch(e){ return localRaw; }
    try{ S = JSON.parse(serverRaw); }catch(e){ return localRaw; }
    if(!Array.isArray(L) || !Array.isArray(S)) return localRaw;
    const have = {};
    L.forEach(function(v){ have[String((v && v.word) || "").toLowerCase()] = true; });
    const out = L.slice();
    S.forEach(function(v){
      const key = String((v && v.word) || "").toLowerCase();
      if(key && !have[key]){ out.push(v); have[key] = true; }
    });
    return JSON.stringify(out);
  }

  function mergeHistory(localRaw, serverRaw){
    let L, S;
    try{ L = JSON.parse(localRaw); }catch(e){ return localRaw; }
    try{ S = JSON.parse(serverRaw); }catch(e){ return localRaw; }
    if(!Array.isArray(L) || !Array.isArray(S)) return localRaw;
    const map = {};
    L.concat(S).forEach(function(v){
      if(!v || !v.dir) return;
      const old = map[v.dir];
      if(!old || Number(v.at) > Number(old.at)) map[v.dir] = v;
    });
    const out = Object.keys(map).map(function(k){ return map[k]; })
      .sort(function(a, b){ return Number(b.at) - Number(a.at); }).slice(0, 12);
    return JSON.stringify(out);
  }

  function mergeValue(key, localRaw, serverRaw){
    if(key.indexOf(STATE_PREFIX) === 0) return mergeState(localRaw, serverRaw);
    if(key === "listening_workbench_vocab_v1") return mergeVocab(localRaw, serverRaw);
    if(key === "listening_workbench_history_v1") return mergeHistory(localRaw, serverRaw);
    return localRaw;                       // 倍速 / 上次试卷：本地说了算
  }

  function signature(items){
    // 只求「后台这份变没变」，不需要加密哈希
    const text = JSON.stringify(items);
    let h = 2166136261;
    for(let i = 0; i < text.length; i++){
      h ^= text.charCodeAt(i);
      h = (h * 16777619) >>> 0;
    }
    return text.length + ":" + h.toString(16);
  }

  async function restoreHttpData(){
    // 不用 sessionStorage 做一次性闸门：同一标签页里以后还要再合并（靠下面指纹防循环）
    try{
      const res = await fetch("/api/cet6/import", {cache: "no-store"});
      if(!res.ok) return;
      const data = await res.json();
      const items = (data && data.items) || {};
      const keys = Object.keys(items).filter(function(k){ return k.indexOf(PREFIX) === 0; });
      let changed = 0;
      if(keys.length){
        const sig = signature(items);
        let seen = "";
        try{ seen = localStorage.getItem(MERGE_SIG_KEY) || ""; }catch(e){}
        if(sig !== seen){
          keys.forEach(function(k){
            try{
              const localRaw = localStorage.getItem(k);
              if(localRaw == null){
                localStorage.setItem(k, items[k]);
                changed += 1;
                return;
              }
              if(localRaw === items[k]) return;
              const merged = mergeValue(k, localRaw, items[k]);
              if(merged !== localRaw){
                localStorage.setItem(k, merged);
                changed += 1;
              }
            }catch(e){}
          });
          try{ localStorage.setItem(MERGE_SIG_KEY, sig); }catch(e){}
        }
      }
      try{
        if(changed) localStorage.setItem(MARK_RESTORED, new Date().toISOString());
      }catch(e){}
      // 合并后 reload 一次：试卷层/启动器在同步执行，等不了 fetch 回来
      if(changed) location.reload();
    }catch(e){
      console.warn("从学习系统恢复六级进度失败：", e);
    }
  }

  function retired(){
    return !!(WB.FLAGS && WB.FLAGS.retired);
  }

  function updateFooter(){
    const node = document.querySelector("footer");
    if(!node) return;
    if(retired() && isFile()){
      node.textContent = "只读模式 · 进度以学习系统为准 · 可以查看和导出，不能修改";
      return;
    }
    if(isHttp()){
      node.textContent = "已接入学习系统 · 从文件夹打开也会跳到这一份 · AI 分析走统一后台";
    }
  }

  // 后台开着时，双击文件夹里的 HTML 也跳到同一个 HTTP 工作台 ——
  // 一份 localStorage、一个地址，file:// 和 /cet6/ 才不会各记各的进度。
  function probeServer(base, timeoutMs){
    return new Promise(function(resolve){
      let settled = false;
      const ctrl = (typeof AbortController !== "undefined") ? new AbortController() : null;
      const finish = function(ok){
        if(settled) return;
        settled = true;
        resolve(ok);
      };
      const timer = setTimeout(function(){
        if(ctrl) { try{ ctrl.abort(); }catch(e){} }
        finish(false);
      }, timeoutMs);
      const options = {mode:"no-cors", cache:"no-store"};
      if(ctrl) options.signal = ctrl.signal;
      fetch(base + "/cet6/", options).then(function(){
        clearTimeout(timer);
        finish(true);
      }).catch(function(){
        clearTimeout(timer);
        finish(false);
      });
    });
  }

  async function jumpToServer(){
    if(!isFile()) return false;
    if(sessionStorage.getItem(REDIRECT_GUARD) === "1") return false;   // 跳过一次还失败就别循环
    for(let i = 0; i < SERVERS.length; i++){
      if(!(await probeServer(SERVERS[i], 800))) continue;
      // 跳之前先把本地这份推上去：离线期间在文件夹里记的进度，后台一开就能补进同一份。
      // 退休后 file:// 不再作为写入口，只跳转、不推送。
      if(!retired()) await importFileData(collectAll(), SERVERS[i]);
      try{ sessionStorage.setItem(REDIRECT_GUARD, "1"); }catch(e){}
      location.replace(SERVERS[i] + "/cet6/" + (location.hash || ""));
      return true;
    }
    return false;
  }

  updateFooter();
  if(isFile()){
    jumpToServer().then(function(jumped){
      // 后台没开：退休前照旧把本地数据推上去；退休后只读，不推送。
      if(!jumped && !retired()) importFileData(collectAll());
    });
  }else if(isHttp() && !retired()){
    // 退休后由 58-sync 在 boot 时按试卷从 cet6_progress 恢复，不再合并 legacy 快照。
    restoreHttpData();
  }
})(window.WB = window.WB || {});
