// @requires: 00-core.js, 10-storage.js, 20-paper.js, 40-render.js, 55-api.js
// 功能层：生词本存储、面板、划词浮钮与 CSV 导出。
// HTTP 模式（学习工作台 /cet6/）以服务端 vocab_items 为唯一真源；
// file:// 模式仍用 localStorage，保持旧入口可用。
(function(WB){
  "use strict";

  const U = WB.util;
  const MIGRATED_KEY = "listening_workbench_vocab_migrated_v2";
  let bound = false;
  let remote = null;       // HTTP 模式下的服务端快照（null = 还没拉到）
  let remoteReady = false;
  let meaningTimer = null;

  function usingApi(){
    return !!(WB.api && WB.api.HTTP && WB.api.ready);
  }

  // 面板渲染始终同步：HTTP 用服务端快照，file:// 用 localStorage。
  function load(){
    return remote || WB.store.loadVocab();
  }

  function mapRemote(item){
    return {
      id: item.id,
      word: item.word,
      meaning: item.meaning || "",
      context: item.context || "",
      paper: item.paper_title || "",
      at: item.created_at || ""
    };
  }

  async function migrateOnce(){
    if(!usingApi()) return;
    let done = false;
    try{ done = localStorage.getItem(MIGRATED_KEY) === "1"; }catch(e){}
    if(done) return;
    const local = WB.store.loadVocab();
    if(local.length){
      try{
        const result = await WB.api.post("/api/vocab/import", {items: local});
        WB.status("生词已迁入学习工作台：新增 " + result.added + "，合并 " + result.merged);
      }catch(e){
        // 迁移失败不落标记，下次打开再试
        return;
      }
    }
    try{ localStorage.setItem(MIGRATED_KEY, "1"); }catch(e){}
  }

  async function refresh(){
    if(!usingApi()){ remote = null; remoteReady = false; return false; }
    await migrateOnce();
    try{
      const data = await WB.api.get("/api/vocab?limit=500");
      remote = (data.items || []).map(mapRemote);
      remoteReady = true;
      return true;
    }catch(e){
      WB.status("生词本读取失败：" + WB.api.errorText(e));
      return false;
    }
  }

  function syncFromServer(){
    return refresh().then(function(ok){
      if(ok && WB.dom.vocabPanel && !WB.dom.vocabPanel.classList.contains("hidden")){
        render();
      }
      return ok;
    });
  }

  function render(){
    const body = WB.dom.vocabBody;
    const arr = load();
    if(!arr.length){
      body.innerHTML = '<p class="status">还没有生词。先点“显示原文”，选中一个单词，再点“收藏生词”。</p>';
      return;
    }
    body.innerHTML = arr.map(function(v, k){
      return '<div class="vocab-row" data-k="' + k + '">' +
        '<span class="w">' + U.escapeHtml(v.word) + "</span>" +
        '<input data-meaning="' + k + '" placeholder="释义 / 备注" value="' +
          U.escapeHtml(v.meaning || "") + '">' +
        '<span class="ctx">' + U.escapeHtml(v.context || "") + "</span>" +
        '<button data-del="' + k + '">删除</button></div>';
    }).join("");
  }

  // 生词本唯一的写入入口：划词翻译和「＋生词」都走这里。
  // 已存在时只补/更新释义，不再重复插入。
  async function addWord(word, meaning, context){
    if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("生词本")) return false;
    word = String(word || "").trim();
    if(!word || word.length > 60){
      alert("请选择一个单词或短语（不超过 60 字）。");
      return false;
    }

    if(usingApi()){
      const hit = load().find(function(v){
        return String(v.word || "").toLowerCase() === word.toLowerCase();
      });
      try{
        const data = await WB.api.post("/api/vocab", {
          word: word,
          meaning: String(meaning || ""),
          context: String(context || "").slice(0, 500),
          paper_id: WB.session.paperDir || (WB.session.paper && WB.session.paper.title) || "",
          paper_title: (WB.session.paper && WB.session.paper.title) || "",
          source: "cet6"
        });
        await refresh();
        render();
        if(data.created){
          WB.status("已加入生词本：" + word);
        }else if(meaning && hit && !hit.meaning){
          WB.status("生词本里已有「" + word + "」，已补上释义。");
        }else{
          WB.status("生词本里已经有「" + word + "」了。");
        }
        return !!data.created;
      }catch(e){
        WB.status("生词本写入失败：" + WB.api.errorText(e));
        return false;
      }
    }

    const arr = WB.store.loadVocab();
    const hit = arr.find(function(v){
      return String(v.word || "").toLowerCase() === word.toLowerCase();
    });
    if(hit){
      if(meaning && !hit.meaning){
        hit.meaning = String(meaning);
        WB.store.saveVocab(arr);
        WB.status("生词本里已有「" + word + "」，已补上释义。");
      }else{
        WB.status("生词本里已经有「" + word + "」了。");
      }
      return false;
    }
    arr.unshift({
      word: word, meaning: String(meaning || ""), context: String(context || "").slice(0, 500),
      paper: WB.session.paper.title, at: new Date().toISOString()
    });
    WB.store.saveVocab(arr);
    WB.status("已加入生词本：" + word);
    return true;
  }

  function addSelection(){
    const selObj = window.getSelection ? window.getSelection() : null;
    const sel = selObj ? String(selObj.toString() || "").trim() : "";
    if(!sel || sel.length > 60){
      alert("先在已显示的原文里选中一个单词或短语（不超过 60 字）。");
      return;
    }
    let context = "";
    const node = selObj.anchorNode;
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    const card = el && el.closest ? el.closest(".card") : null;
    if(card){
      const s = WB.paper.findSentence(Number(card.dataset.i));
      if(s) context = s.en;
    }
    addWord(sel, "", context);
  }

  function togglePanel(){
    const panel = WB.dom.vocabPanel;
    if(panel.classList.contains("hidden")){
      panel.classList.remove("hidden");
      if(usingApi() && !remoteReady){
        refresh().then(render);
      }else{
        render();
      }
    }else{
      panel.classList.add("hidden");
    }
  }

  function exportCsv(){
    if(usingApi()){
      WB.api.download("/api/vocab/export.csv", "生词本.csv").catch(function(e){
        WB.status("导出失败：" + WB.api.errorText(e));
      });
      return;
    }
    const arr = WB.store.loadVocab();
    if(!arr.length){ alert("生词本是空的。"); return; }
    const q = function(x){ return '"' + String(x || "").replace(/"/g, '""') + '"'; };
    const lines = ["单词,释义,上下文,试卷,添加时间"];
    arr.forEach(function(v){
      lines.push([v.word, v.meaning, v.context, v.paper, v.at].map(q).join(","));
    });
    const blob = new Blob(["﻿" + lines.join("\n")], {type:"text/csv;charset=utf-8"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "生词本.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function init(){
    if(bound) return;
    bound = true;

    document.getElementById("vocabAddBtn").addEventListener("click", addSelection);
    WB.dom.selVocabBtn.addEventListener("mousedown", function(e){ e.preventDefault(); });
    WB.dom.selVocabBtn.addEventListener("click", function(){
      addSelection();
      WB.dom.selVocabBtn.classList.add("hidden");
    });

    document.getElementById("vocabBtn").addEventListener("click", togglePanel);
    document.getElementById("closeVocab").addEventListener("click", function(){
      WB.dom.vocabPanel.classList.add("hidden");
    });

    WB.dom.vocabBody.addEventListener("input", function(e){
      const inp = e.target.closest("input[data-meaning]");
      if(!inp) return;
      const k = Number(inp.dataset.meaning);
      const arr = load();
      const item = arr[k];
      if(!item) return;
      if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("生词释义")) return;
      item.meaning = inp.value;
      if(item.id && usingApi()){
        clearTimeout(meaningTimer);
        meaningTimer = setTimeout(function(){
          WB.api.patch("/api/vocab/" + item.id, {meaning: item.meaning}).catch(function(err){
            WB.status("释义保存失败：" + WB.api.errorText(err));
          });
        }, 500);
        return;
      }
      const local = WB.store.loadVocab();
      if(local[k]){
        local[k].meaning = inp.value;
        WB.store.saveVocab(local);
      }
    });

    WB.dom.vocabBody.addEventListener("click", async function(e){
      const b = e.target.closest("button[data-del]");
      if(!b) return;
      const k = Number(b.dataset.del);
      if(WB.cet6Mode && !WB.cet6Mode.ensureWritable("生词本")) return;
      const item = load()[k];
      if(item && item.id && usingApi()){
        try{
          await WB.api.del("/api/vocab/" + item.id);
        }catch(err){
          WB.status("删除失败：" + WB.api.errorText(err));
          return;
        }
        await refresh();
      }else{
        const local = WB.store.loadVocab();
        local.splice(k, 1);
        WB.store.saveVocab(local);
      }
      render();
    });

    document.getElementById("exportVocab").addEventListener("click", exportCsv);
  }

  WB.vocab = {
    init: init,
    render: render,
    addWord: addWord,
    addSelection: addSelection,
    exportCsv: exportCsv,
    syncFromServer: syncFromServer
  };
})(window.WB = window.WB || {});
