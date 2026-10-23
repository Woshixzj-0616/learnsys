// @requires: 00-core.js, 04-mode.js
// 双写审计的纯函数：服务端行 → 本地状态、整卷快照、结构指纹、空快照判断。
// 不碰网络、不碰 DOM，node --test 可直接加载。
(function(WB){
  "use strict";

  function normText(text){
    return String(text || "").toLowerCase()
      .replace(/\s+/g, "")
      .replace(/[·:：,，.。;；!！?？'"“”‘’()（）\[\]【】]/g, "");
  }

  function sectionLetter(name){
    const m = String(name || "").match(/Section\s*([A-Za-z])/i);
    return m ? m[1].toUpperCase() : "";
  }

  function tailNumber(text){
    const m = String(text || "").match(/(\d+)\s*$/);
    return m ? Number(m[1]) : null;
  }

  function pickSection(sections, name){
    const list = sections || [];
    const exact = list.filter(function(sec){ return sec.name === name; });
    if(exact.length === 1) return exact[0];
    if(exact.length > 1) return null;
    const letter = sectionLetter(name);
    if(!letter) return null;
    const byLetter = list.filter(function(sec){ return sec.letter === letter; });
    return byLetter.length === 1 ? byLetter[0] : null;
  }

  function pickItem(section, title){
    const items = (section && section.items) || [];
    const exact = items.filter(function(it){ return it.title === title; });
    if(exact.length === 1) return exact[0];
    if(exact.length > 1) return null;
    const num = tailNumber(title);
    if(num != null){
      const byNum = items.filter(function(it){ return Number(it.index) === num; });
      if(byNum.length === 1) return byNum[0];
    }
    const norm = normText(title);
    const byNorm = items.filter(function(it){ return normText(it.title) === norm; });
    return byNorm.length === 1 ? byNorm[0] : null;
  }

  function emptyMaps(){
    return {done:{}, errors:{}, notes:{}, loopStats:{}};
  }

  function put(map, id, sentence, value){
    if(!map[id]) map[id] = {};
    map[id][sentence] = value;
  }

  // 服务端整卷行 → 本地 state 形状；歧义/结构对不上一律不猜。
  // 返回的 skipped 会随 /api/cet6/sync-paper 回传，服务端据此保留旧行。
  function mapServerState(paper, serverItems){
    const state = emptyMaps();
    const skipped = [];
    let meaningful = 0, matched = 0, partial = 0, unmatched = 0;
    const sections = (paper && paper.sections) || [];

    (serverItems || []).forEach(function(group){
      const sec = pickSection(sections, group && group.section);
      const item = sec ? pickItem(sec, group && group.item) : null;
      if(!sec || !item){
        unmatched += 1;
        skipped.push({section: String((group && group.section) || ""),
                      item: String((group && group.item) || ""),
                      reason: "结构未匹配"});
        return;
      }
      const id = sec.letter + "-" + item.index;
      const valid = {};
      (item.sentences || []).forEach(function(sent){ valid[sent.i] = true; });
      let bad = false;
      (group.sentences || []).forEach(function(row){
        if(!valid[row.sentence]){ bad = true; return; }
        if(row.done) put(state.done, id, row.sentence, true);
        if(row.tags && row.tags.length){
          put(state.errors, id, row.sentence, row.tags.slice());
        }
        if(row.note) put(state.notes, id, row.sentence, String(row.note));
        const loops = Number(row.loops) || 0;
        const plays = Number(row.plays) || 0;
        if(loops || plays) put(state.loopStats, id, row.sentence, {loops:loops, plays:plays});
        if(row.done || (row.tags && row.tags.length) || row.note || loops) meaningful += 1;
      });
      if(bad){
        partial += 1;
        skipped.push({section: group.section, item: group.item, reason: "句子结构不一致"});
      }else{
        matched += 1;
      }
    });
    return {state:state, skipped:skipped, meaningful:meaningful,
            matched:matched, partial:partial, unmatched:unmatched};
  }

  function mergeMaps(dst, src, mode){
    Object.keys(src || {}).forEach(function(id){
      const source = src[id] || {};
      const target = dst[id] || (dst[id] = {});
      Object.keys(source).forEach(function(key){
        if(mode === "union"){
          if(mode === "union" && Array.isArray(source[key])){
            const arr = target[key] || [];
            source[key].forEach(function(v){ if(arr.indexOf(v) < 0) arr.push(v); });
            if(arr.length) target[key] = arr;
          }else if(target[key] == null || source[key] === true){
            target[key] = source[key];
          }
        }else if(mode === "missing"){
          if(target[key] == null) target[key] = source[key];
        }else{
          target[key] = source[key];
        }
      });
    });
  }

  // 把服务端状态并进本地 state。
  // serverFirst=false：本地优先，只补缺口（双写阶段）。
  // serverFirst=true ：服务端优先（退休后），但 done/errors 仍取并集，防止误删。
  function mergeIntoState(state, mapped, serverFirst){
    if(!state || !mapped || !mapped.state) return false;
    state.done = state.done || {};
    state.errors = state.errors || {};
    state.notes = state.notes || {};
    state.loopStats = state.loopStats || {};
    const before = JSON.stringify({done:state.done, errors:state.errors,
                                   notes:state.notes, loopStats:state.loopStats});
    mergeMaps(state.done, mapped.state.done, "union");
    mergeMaps(state.errors, mapped.state.errors, "union");
    mergeMaps(state.notes, mapped.state.notes, serverFirst ? "override" : "missing");
    const statsDst = state.loopStats;
    Object.keys(mapped.state.loopStats || {}).forEach(function(id){
      const src = mapped.state.loopStats[id] || {};
      const dst = statsDst[id] || (statsDst[id] = {});
      Object.keys(src).forEach(function(sentence){
        const a = dst[sentence] || {};
        const b = src[sentence] || {};
        dst[sentence] = {loops:Math.max(Number(a.loops) || 0, Number(b.loops) || 0),
                         plays:Math.max(Number(a.plays) || 0, Number(b.plays) || 0)};
      });
    });
    const after = JSON.stringify({done:state.done, errors:state.errors,
                                  notes:state.notes, loopStats:state.loopStats});
    return before !== after;
  }

  function canonicalRows(paper, state, skipped){
    const skip = {};
    (skipped || []).forEach(function(item){
      skip[String(item.section) + "\u0000" + String(item.item)] = true;
    });
    const items = [];
    const sections = (paper && paper.sections) || [];
    sections.forEach(function(sec){
      (sec.items || []).forEach(function(item){
        if(skip[String(sec.name) + "\u0000" + String(item.title)]) return;
        const id = sec.letter + "-" + item.index;
        const doneMap = (state && state.done && state.done[id]) || {};
        const errors = (state && state.errors && state.errors[id]) || {};
        const notes = (state && state.notes && state.notes[id]) || {};
        const stats = (state && state.loopStats && state.loopStats[id]) || {};
        const done = [];
        const sentences = (item.sentences || []).map(function(sent){
          if(doneMap[sent.i]) done.push(sent.i);
          const st = stats[sent.i] || {};
          return {
            sentence: sent.i,
            en: sent.en || "",
            tags: (errors[sent.i] || []).slice(),
            note: notes[sent.i] || "",
            loops: Number(st.loops) || 0,
            plays: Number(st.plays) || 0
          };
        });
        items.push({section: sec.name, item: item.title,
                    sentences: sentences, done: done});
      });
    });
    return {items: items};
  }

  function anyMap(map){
    return Object.keys(map || {}).some(function(id){
      const inner = map[id];
      return inner && typeof inner === "object" && Object.keys(inner).length > 0;
    });
  }

  function anyLoop(stats){
    return Object.keys(stats || {}).some(function(id){
      const inner = stats[id] || {};
      return Object.keys(inner).some(function(sentence){
        const st = inner[sentence] || {};
        return (Number(st.loops) || 0) > 0 || (Number(st.plays) || 0) > 0;
      });
    });
  }

  // 只看 4 个同步字段；starts / ab / pos / 翻译缓存不算「有进度」。
  function snapshotIsEmpty(state){
    if(!state) return true;
    return !(anyMap(state.done) || anyMap(state.errors) ||
             anyMap(state.notes) || anyLoop(state.loopStats));
  }

  function paperSig(paper){
    const text = ((paper && paper.sections) || []).map(function(sec){
      return String(sec.letter) + "|" + String(sec.name) + "|" +
        (sec.items || []).map(function(item){
          return String(item.index) + "|" + String(item.title) + "|" +
            (item.sentences || []).map(function(s){ return s.i; }).join(",");
        }).join(";");
    }).join("||");
    let h = 2166136261;
    for(let i = 0; i < text.length; i++){
      h ^= text.charCodeAt(i);
      h = (h * 16777619) >>> 0;
    }
    return text.length + ":" + h.toString(16);
  }

  function clientDay(){
    const d = new Date();
    const pad = function(n){ return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  WB.dualwrite = {
    normText: normText,
    sectionLetter: sectionLetter,
    tailNumber: tailNumber,
    pickSection: pickSection,
    pickItem: pickItem,
    mapServerState: mapServerState,
    mergeIntoState: mergeIntoState,
    canonicalRows: canonicalRows,
    snapshotIsEmpty: snapshotIsEmpty,
    paperSig: paperSig,
    clientDay: clientDay
  };
})(window.WB = window.WB || {});
