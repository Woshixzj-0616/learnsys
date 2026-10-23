// @requires: 00-core.js, 10-storage.js, 20-paper.js, 30-audio.js, 40-render.js, 50-actions.js, 55-api.js, 58-sync.js
// 功能层：分析任务状态机、自由提问的上下文、学习统计。
// 收起分析只隐藏面板，结果留在 state.analysis；刷新后从后台恢复最近一条。
(function(WB){
  "use strict";

  const U = WB.util;
  const HTTP = location.protocol === "http:" || location.protocol === "https:";
  const LEGACY_ANALYZE = "http://127.0.0.1:8765/analyze";
  const PAPER_KEY = "__paper__";

  let bound = false;
  let seq = 0;
  let pollTimer = null;
  let statusTimer = null;
  let busy = false;

  function S(){ return WB.session; }
  function currentKey(){ return WB.paper.currentItemId(); }
  function isPaperKey(key){ return key === PAPER_KEY; }
  function hasAnalysis(key){ return !!(WB.state.analysis[key]); }

  function paperInfo(){
    return {
      paper: WB.session.paper.title,
      paper_id: WB.session.paperDir || WB.session.paper.title
    };
  }

  function collectRecord(){
    const sec = WB.paper.currentSection();
    const cur = WB.paper.currentItem();
    const id = WB.paper.currentItemId();
    const errors = WB.state.errors[id] || {};
    const notes = WB.state.notes[id] || {};
    const stats = WB.state.loopStats[id] || {};
    const rows = [];
    cur.sentences.forEach(function(s){
      const tags = errors[s.i] || [];
      const note = (notes[s.i] || "").trim();
      const st = stats[s.i] || {};
      const loops = Number(st.loops) || 0;
      const plays = Number(st.plays) || 0;
      if(tags.length || note || loops > 0){
        rows.push({
          sentence: s.i, en: s.en, tags: tags, note: note,
          start: s.start, loops: loops, plays: plays
        });
      }
    });
    return {
      paper: WB.session.paper.title,
      paper_id: WB.session.paperDir || WB.session.paper.title,
      section: sec.name,
      item: cur.title,
      sentences: rows
    };
  }

  function collectPaperRows(){
    const rows = [];
    WB.session.paper.sections.forEach(function(sec){
      sec.items.forEach(function(cur){
        const id = WB.paper.itemId(sec, cur);
        const errs = WB.state.errors[id] || {};
        const notes = WB.state.notes[id] || {};
        const stats = WB.state.loopStats[id] || {};
        cur.sentences.forEach(function(s){
          const tags = errs[s.i] || [];
          const note = (notes[s.i] || "").trim();
          const st = stats[s.i] || {};
          const loops = Number(st.loops) || 0;
          const plays = Number(st.plays) || 0;
          if(tags.length || note || loops > 0){
            rows.push({
              sentence: s.i, en: s.en, tags: tags, note: note, start: s.start,
              loops: loops, plays: plays,
              section: sec.name, item: cur.title
            });
          }
        });
      });
    });
    return rows;
  }

  function downloadRecord(record){
    const blob = new Blob([JSON.stringify(record, null, 2)],
      {type:"application/json;charset=utf-8"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "学习记录-" + U.safeName(record.paper) + "-" +
      U.safeName(record.section || "") + "-" + U.safeName(record.item || "") + ".json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function analysisViewActive(){
    return !!(WB.dom.askAnalysisView &&
      !WB.dom.askAnalysisView.classList.contains("hidden"));
  }

  function showDot(on){
    if(WB.dom.analysisDot) WB.dom.analysisDot.classList.toggle("hidden", !on);
  }

  function showPanel(){
    WB.dom.analysisPanel.classList.remove("hidden");
    if(WB.dom.analysisEmpty) WB.dom.analysisEmpty.classList.add("hidden");
    showDot(false);
  }

  function hidePanel(showHint, forceKey){
    const key = forceKey || S().panelKey || currentKey();
    if(analysisViewActive()){
      // 正停在「分析」页：把上次结果留在眼前，不因为换段/收起而突然空白。
      if(hasAnalysis(key)){
        WB.dom.analysisPanel.classList.remove("hidden");
        if(WB.dom.analysisEmpty) WB.dom.analysisEmpty.classList.add("hidden");
      }else{
        WB.dom.analysisPanel.classList.add("hidden");
        if(WB.dom.analysisEmpty) WB.dom.analysisEmpty.classList.remove("hidden");
      }
      showDot(false);
      return;
    }
    WB.dom.analysisPanel.classList.add("hidden");
    showDot(!!(showHint && hasAnalysis(key)));
  }

  function actionsHtml(items){
    if(!items || !items.length) return "";
    const fallback = {cancel:"取消", retry:"重试", old:"打开上次",
                      "rerun-item":"重新分析", "rerun-paper":"重新分析"};
    return '<div class="analysis-actions">' + items.map(function(x){
      return '<button type="button" data-analysis-act="' + x.act + '"' +
        (x.id != null ? ' data-id="' + Number(x.id) + '"' : "") + ">" +
        U.escapeHtml(x.label || fallback[x.act] || "操作") + "</button>";
    }).join("") + "</div>";
  }

  function stopStatusTimer(){
    if(statusTimer){ clearInterval(statusTimer); statusTimer = null; }
  }

  function setStatus(key, text, actions, startedAt){
    S().panelKey = key;
    S().analysisHidden = false;
    showPanel();
    WB.dom.analysisBody.innerHTML =
      '<div class="analysis-status"><p>' + U.escapeHtml(text) + "</p>" +
      actionsHtml(actions) + "</div>";
    stopStatusTimer();
    if(startedAt){
      statusTimer = setInterval(function(){
        const p = WB.dom.analysisBody.querySelector(".analysis-status p");
        if(!p){ stopStatusTimer(); return; }
        p.textContent = "分析中 · 已用 " +
          Math.round((Date.now() - startedAt) / 1000) + " 秒";
      }, 1000);
    }
  }

  function renderAnalysis(forceKey, keepHidden){
    const key = forceKey || currentKey();
    S().panelKey = key;
    const a = WB.state.analysis[key];
    const panel = WB.dom.analysisPanel;
    const body = WB.dom.analysisBody;
    if(!a){
      panel.classList.add("hidden");
      showDot(false);
      body.innerHTML = "";
      if(WB.dom.analysisEmpty) WB.dom.analysisEmpty.classList.remove("hidden");
      return;
    }
    if(WB.dom.analysisEmpty) WB.dom.analysisEmpty.classList.add("hidden");
    const parts = [actionsHtml([
      {act: isPaperKey(key) ? "rerun-paper" : "rerun-item", label:"重新分析"}
    ])];
    if(a.summary) parts.push("<p>" + U.escapeHtml(a.summary) + "</p>");
    if(Array.isArray(a.patterns) && a.patterns.length){
      parts.push("<h3>主要问题</h3>");
      a.patterns.forEach(function(p){
        parts.push(
          '<div class="pattern"><b>' + U.escapeHtml(p.name || "") + "</b>" +
          (p.evidence ? "<p>证据：" + U.escapeHtml(p.evidence) + "</p>" : "") +
          (p.advice ? "<p>建议：" + U.escapeHtml(p.advice) + "</p>" : "") +
          "</div>"
        );
      });
    }
    if(Array.isArray(a.priority) && a.priority.length){
      parts.push("<h3>优先回听</h3><div class='priority'>");
      a.priority.forEach(function(p){
        parts.push('<button data-priority="' + Number(p.sentence) + '" title="' +
          U.escapeHtml(p.reason || "") + '">第 ' + Number(p.sentence) + " 句</button>");
      });
      parts.push("</div>");
      a.priority.forEach(function(p){
        if(p.reason){
          parts.push('<p class="status">第 ' + Number(p.sentence) + " 句：" +
            U.escapeHtml(p.reason) + "</p>");
        }
      });
    }
    if(Array.isArray(a.plan) && a.plan.length){
      parts.push("<h3>练习计划</h3><ol class='plan'>");
      a.plan.forEach(function(x){ parts.push("<li>" + U.escapeHtml(x) + "</li>"); });
      parts.push("</ol>");
    }
    if(a.model) parts.push('<p class="status">分析模型：' + U.escapeHtml(a.model) + "</p>");
    body.innerHTML = parts.join("");
    if(keepHidden || S().analysisHidden) hidePanel(true);
    else showPanel();
  }

  function stopPoll(){
    if(pollTimer){ clearTimeout(pollTimer); pollTimer = null; }
    stopStatusTimer();
  }

  function poll(id, key, my, started){
    pollTimer = setTimeout(function(){
      if(my !== seq) return;
      WB.api.get("/api/cet6/analysis/" + id).then(function(row){
        if(my !== seq) return;
        if(row.status === "done"){
          WB.state.analysis[key] = row.content;
          WB.store.saveState();
          WB.cet6Sync.push(row.content);
          S().analysisHidden = false;
          renderAnalysis(key);
        }else if(row.status === "pending" || row.status === "running"){
          setStatus(key, "分析中 · 已用 " + Math.round((Date.now() - started) / 1000) +
            " 秒", [{act:"cancel", id:id, label:"取消"}], started);
          poll(id, key, my, started);
        }else if(row.status === "error"){
          setStatus(key, "分析失败：" + (row.error || "未知原因"),
            [{act:"retry", label:"重试"}, {act:"old", label:"打开上次"}]);
        }else if(row.status === "canceled"){
          setStatus(key, "已取消。", [{act:"retry", label:"重试"}, {act:"old", label:"打开上次"}]);
        }else{
          poll(id, key, my, started);
        }
      }).catch(function(err){
        if(my !== seq) return;
        setStatus(key, "查询分析结果失败：" + WB.api.errorText(err),
          [{act:"retry", label:"重试"}]);
      });
    }, 800);
  }

  function restoreLatest(){
    const key = currentKey();
    const my = ++seq;
    stopPoll();
    const local = hasAnalysis(key);
    if(local){
      S().analysisHidden = false;
      renderAnalysis(key, true);
    }else{
      S().analysisHidden = false;
      hidePanel(false, key);
    }
    if(!(HTTP && WB.api.ready)) return;
    const sec = WB.paper.currentSection();
    const cur = WB.paper.currentItem();
    const info = paperInfo();
    const query = "?paper_id=" + encodeURIComponent(info.paper_id) +
      "&section=" + encodeURIComponent(sec.name) +
      "&item=" + encodeURIComponent(cur.title) + "&scope=item";
    WB.api.get("/api/cet6/analysis" + query).then(function(row){
      if(my !== seq) return;
      if(!row || row.status === "none"){
        if(!local) hidePanel(false, key);
        return;
      }
      if(row.status === "done" && row.content){
        WB.state.analysis[key] = row.content;
        WB.store.saveState();
        S().analysisHidden = false;
        renderAnalysis(key);
      }else if(row.status === "pending" || row.status === "running"){
        const started = Date.now();
        setStatus(key, "分析中 · 已用 0 秒", [{act:"cancel", id:row.id, label:"取消"}], started);
        poll(row.id, key, my, started);
      }else if(row.status === "error"){
        setStatus(key, "上次分析失败：" + (row.error || "未知原因"),
          [{act:"retry", label:"重试"}, {act:"old", label:"打开上次"}]);
      }else if(row.status === "canceled"){
        setStatus(key, "上次分析已取消。", [{act:"retry", label:"重试"}, {act:"old", label:"打开上次"}]);
      }
    }).catch(function(){});
  }

  function setButtonBusy(on){
    const itemBtn = document.getElementById("aiAnalyzeItem");
    const paperBtn = document.getElementById("aiAnalyzePaper");
    if(itemBtn) itemBtn.disabled = !!on;
    if(paperBtn) paperBtn.disabled = !!on;
  }

  async function submitLegacy(record, key, paperScope){
    if(WB.cet6Mode && WB.cet6Mode.readOnly){
      WB.status("只读模式：请从学习工作台打开后再分析。");
      return;
    }
    busy = true;
    setButtonBusy(true);
    const my = ++seq;
    stopPoll();
    setStatus(key, "分析中…请稍候（最长 3 分钟）", []);
    try{
      const body = paperScope ? Object.assign({}, record, {scope:"paper"}) : record;
      const res = await fetch(LEGACY_ANALYZE, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      if(!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      if(data.error) throw new Error(data.error);
      if(my !== seq) return;
      const analysis = data.analysis || data;
      WB.state.analysis[key] = analysis;
      WB.store.saveState();
      WB.cet6Sync.push(analysis);
      S().analysisHidden = false;
      renderAnalysis(key);
    }catch(err){
      if(my !== seq) return;
      downloadRecord(record);
      setStatus(key, "分析服务调用失败。学习记录已导出；请确认学习工作台后台已启动，" +
        "再点「重试」。（" + err.message + "）", [{act:"retry", label:"重试"}]);
    }finally{
      busy = false;
      setButtonBusy(false);
    }
  }

  async function submitRecord(record, key, paperScope, force){
    if(WB.cet6Mode && WB.cet6Mode.readOnly){
      WB.status("只读模式：请从学习工作台打开后再分析。");
      return;
    }
    if(!(HTTP && WB.api.ready)){
      if(HTTP){
        setStatus(key, "后台令牌还没取到，请稍等一下再点「重试」。",
          [{act:"retry", label:"重试"}]);
        return;
      }
      return submitLegacy(record, key, paperScope);
    }
    if(busy) return;
    busy = true;
    setButtonBusy(true);
    const my = ++seq;
    stopPoll();
    setStatus(key, "正在提交分析…", []);
    const info = paperInfo();
    try{
      const submitted = await WB.api.post("/api/cet6/analysis", {
        paper_id: info.paper_id,
        paper: info.paper,
        section: record.section,
        item: record.item,
        scope: paperScope ? "paper" : "item",
        sentences: record.sentences,
        force: !!force
      });
      if(my !== seq) return;
      if(submitted.status === "done"){
        const row = await WB.api.get("/api/cet6/analysis/" + submitted.id);
        if(my !== seq) return;
        WB.state.analysis[key] = row.content;
        WB.store.saveState();
        WB.cet6Sync.push(row.content);
        S().analysisHidden = false;
        renderAnalysis(key);
      }else{
        const started = Date.now();
        setStatus(key, "分析中 · 已用 0 秒",
          [{act:"cancel", id:submitted.id, label:"取消"}], started);
        poll(submitted.id, key, my, started);
      }
    }catch(err){
      if(my !== seq) return;
      setStatus(key, "提交分析失败：" + WB.api.errorText(err),
        [{act:"retry", label:"重试"}]);
    }finally{
      busy = false;
      setButtonBusy(false);
    }
  }

  function submitItem(force){
    const record = collectRecord();
    if(!record.sentences.length){
      alert("先勾选断点、写一句原因，或者把某句反复循环几次，再让模型分析。" +
        "也可以直接在「对话」里自由提问。");
      return;
    }
    submitRecord(record, currentKey(), false, force);
  }

  function analyzePaper(force){
    const rows = collectPaperRows();
    if(!rows.length){
      alert("本卷还没有任何断点、笔记或循环记录，先听几段再来。");
      return;
    }
    const info = paperInfo();
    const record = {
      paper: info.paper, paper_id: info.paper_id,
      section: "整卷", item: "全部", scope: "paper",
      sentences: rows.slice(0, 120)
    };
    submitRecord(record, PAPER_KEY, true, force);
  }

  async function cancelAnalysis(id, key){
    if(!id) return;
    try{ await WB.api.post("/api/cet6/analysis/" + id + "/cancel", {}); }catch(e){}
    stopPoll();
    seq += 1;
    setStatus(key, "已取消。上次结果还在。", [{act:"retry", label:"重试"}, {act:"old", label:"打开上次"}]);
  }

  function renderStats(){
    const body = WB.dom.statsBody;
    const total = WB.paper.totalSentences();
    const done = WB.paper.totalDone();
    const today = new Date().toISOString().slice(0, 10);
    const todayDone = (WB.state.daily || {})[today] || 0;
    let reviewN = 0, noteN = 0, loopTotal = 0;
    const tagCount = {};
    const rows = [];
    WB.session.paper.sections.forEach(function(sec){
      sec.items.forEach(function(cur){
        const id = WB.paper.itemId(sec, cur);
        const d = WB.state.done[id] || {};
        const doneN = Object.keys(d).filter(function(k){ return d[k]; }).length;
        const revN = cur.sentences.filter(function(s){ return s.review; }).length;
        reviewN += revN;
        const errs = WB.state.errors[id] || {};
        Object.keys(errs).forEach(function(si){
          (errs[si] || []).forEach(function(t){ tagCount[t] = (tagCount[t] || 0) + 1; });
        });
        const notes = WB.state.notes[id] || {};
        noteN += Object.keys(notes).filter(function(k){ return (notes[k] || "").trim(); }).length;
        const stats = WB.state.loopStats[id] || {};
        let loops = 0;
        Object.keys(stats).forEach(function(si){ loops += Number(stats[si].loops) || 0; });
        loopTotal += loops;
        rows.push({sec:sec.name, item:cur.title, done:doneN,
                   total:cur.sentences.length, review:revN, loops:loops});
      });
    });
    const tagKeys = Object.keys(tagCount).sort(function(a, b){ return tagCount[b] - tagCount[a]; });
    const tagHtml = tagKeys.length
      ? tagKeys.map(function(t){ return t + " " + tagCount[t]; }).join(" · ")
      : "暂无";
    const parts = [];
    parts.push('<p class="meta">本卷进度 ' + done + " / " + total + " 句 · 今日 " + todayDone +
      " 句 · 待校对 " + reviewN + " 句 · 笔记 " + noteN + " 条 · 循环回绕 " + loopTotal + " 次</p>");
    parts.push("<p><b>断点分布：</b>" + U.escapeHtml(tagHtml) + "</p>");
    parts.push("<table><thead><tr><th>Section / 题型</th><th>已完成</th><th>待校对</th><th>循环</th></tr></thead><tbody>");
    rows.forEach(function(r){
      parts.push("<tr><td>" + U.escapeHtml(r.sec) + " / " + U.escapeHtml(r.item) +
        '</td><td class="n">' + r.done + " / " + r.total +
        '</td><td class="n">' + r.review +
        '</td><td class="n">' + r.loops + "</td></tr>");
    });
    parts.push("</tbody></table>");
    body.innerHTML = parts.join("");
  }

  function toggleStats(){
    const panel = WB.dom.statsPanel;
    if(panel.classList.contains("hidden")){
      renderStats();
      panel.classList.remove("hidden");
    }else{
      panel.classList.add("hidden");
    }
  }

  function init(){
    if(bound) return;
    bound = true;

    const itemBtn = document.getElementById("aiAnalyzeItem");
    if(itemBtn) itemBtn.addEventListener("click", function(){ submitItem(false); });
    const paperBtn = document.getElementById("aiAnalyzePaper");
    if(paperBtn) paperBtn.addEventListener("click", function(){ analyzePaper(false); });

    const closeBtn = document.getElementById("closeAnalysis");
    if(closeBtn) closeBtn.addEventListener("click", function(){
      S().analysisHidden = true;
      hidePanel(true);
      if(WB.ask && WB.ask.showTab) WB.ask.showTab("chat");
    });

    WB.dom.analysisBody.addEventListener("click", function(e){
      const act = e.target.closest("button[data-analysis-act]");
      if(act){
        const kind = act.dataset.analysisAct;
        const id = Number(act.dataset.id || 0);
        const key = S().panelKey || currentKey();
        if(kind === "cancel") cancelAnalysis(id, key);
        else if(kind === "rerun-item") submitItem(true);
        else if(kind === "rerun-paper") analyzePaper(true);
        else if(kind === "retry"){
          if(isPaperKey(key)) analyzePaper(true);
          else submitItem(true);
        }else if(kind === "old"){
          S().analysisHidden = false;
          renderAnalysis(key);
        }
        return;
      }
      const b = e.target.closest("button[data-priority]");
      if(!b) return;
      WB.actions.jumpToSentence(Number(b.dataset.priority));
    });

    document.getElementById("statsBtn").addEventListener("click", toggleStats);
    document.getElementById("closeStats").addEventListener("click", function(){
      WB.dom.statsPanel.classList.add("hidden");
    });
  }

  function showCurrent(){
    const key = S().panelKey || currentKey();
    if(hasAnalysis(key)){
      renderAnalysis(key);
    }else{
      WB.dom.analysisPanel.classList.add("hidden");
      if(WB.dom.analysisEmpty) WB.dom.analysisEmpty.classList.remove("hidden");
    }
  }

  WB.insights = {
    init: init,
    collectRecord: collectRecord,
    renderAnalysis: renderAnalysis,
    restoreLatest: restoreLatest,
    showCurrent: showCurrent,
    submitItem: submitItem,
    analyzePaper: analyzePaper,
    renderStats: renderStats,
    toggleStats: toggleStats
  };
})(window.WB = window.WB || {});
