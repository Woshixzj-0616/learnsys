// @requires: 00-core.js, 10-storage.js, 20-paper.js, 25-ranges.js, 55-api.js
// AI 助手：右下角常驻入口 + 右侧抽屉，任何滚动位置都能用。
// 「对话」是主入口（自由提问，自动带当前试卷/题型/当前句/划词/循环/笔记）；
// 「分析」是可选工具；「历史」从服务端 conversations 读取，可点回旧对话继续。
(function(WB){
  "use strict";

  const U = WB.util;
  let bound = false;
  let historyRows = [];
  let historyQuery = "";
  let historyLoading = false;
  let fabDrag = null;
  let suppressFabClick = false;

  function S(){ return WB.session; }

  function el(tag, className, text){
    const node = document.createElement(tag);
    if(className) node.className = className;
    if(text != null) node.textContent = text;
    return node;
  }

  // 轻量 Markdown：只处理粗体、行内代码、标题和换行；先转义，避免注入。
  function mdLite(text){
    let html = U.escapeHtml(text || "");
    html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/^#{1,4}\s+(.+)$/gm, "<b>$1</b>");
    return html.replace(/\n/g, "<br>");
  }

  function scrollBottom(){
    const body = WB.dom.askBody;
    if(body) body.scrollTop = body.scrollHeight;
  }

  function append(role, text, opts){
    opts = opts || {};
    const wrap = el("div", "ask-msg " + role);
    if(opts.meta){
      wrap.appendChild(el("div", "ask-meta", opts.meta));
    }
    if(opts.thinking){
      const det = el("details", "ask-thinking");
      det.appendChild(el("summary", "", "思考过程"));
      det.appendChild(el("div", "", ""));
      det.lastChild.innerHTML = mdLite(opts.thinking);
      wrap.appendChild(det);
    }
    const bubble = el("div", "ask-bubble");
    bubble.innerHTML = opts.html ? text : mdLite(text);
    wrap.appendChild(bubble);
    WB.dom.askBody.appendChild(wrap);
    scrollBottom();
    return {wrap: wrap, bubble: bubble};
  }

  function clearMessages(){
    if(WB.dom.askBody) WB.dom.askBody.innerHTML = "";
  }

  function welcome(){
    clearMessages();
    WB.dom.askBody.innerHTML =
      '<div class="ai-welcome">' +
        '<b>AI 助手</b>' +
        '<p>不用先勾断点，直接问。会自动带上当前试卷、题型、当前句和你的笔记。</p>' +
        '<p class="status">例如：这一句为什么听不出来 / 这段在讲什么 / 帮我总结本段的考点 / 这个词在句子里怎么理解。</p>' +
      "</div>";
    renderSuggest();
    scrollBottom();
  }

  const SUGGESTS = [
    "这一句为什么听不出来？",
    "这段在讲什么？",
    "帮我总结本段的考点"
  ];

  function renderSuggest(){
    const box = WB.dom.askSuggest;
    if(!box) return;
    box.innerHTML = SUGGESTS.map(function(text){
      return '<button type="button" data-suggest="' + U.escapeHtml(text) + '">' +
        U.escapeHtml(text) + "</button>";
    }).join("");
  }

  function setStreaming(on){
    S().askStreaming = !!on;
    if(WB.dom.askSend) WB.dom.askSend.classList.toggle("hidden", !!on);
    if(WB.dom.askStop) WB.dom.askStop.classList.toggle("hidden", !on);
  }

  function currentId(){
    const ai = WB.store.loadAi();
    if(ai.conversationId) return Number(ai.conversationId) || 0;
    // 兼容旧版本按试卷存的会话 id：第一次打开时并到全局。
    const legacy = Number(WB.state && WB.state.cet6ConversationId) || 0;
    if(legacy){
      WB.store.saveAi({conversationId: legacy});
      return legacy;
    }
    return 0;
  }

  function setConversationId(id){
    WB.store.saveAi({conversationId: Number(id) || 0});
  }

  function selectionInfo(){
    const saved = S().askSelection;
    if(saved && saved.text){
      return {
        text: String(saved.text || "").slice(0, 2000),
        sentence: saved.i != null && saved.i >= 0 ? WB.paper.findSentence(Number(saved.i)) : null,
        i: saved.i != null ? Number(saved.i) : -1
      };
    }
    const selObj = window.getSelection ? window.getSelection() : null;
    const sel = selObj ? String(selObj.toString() || "").trim() : "";
    if(!sel || !selObj.anchorNode) return {text: "", sentence: null, i: -1};
    const node = selObj.anchorNode;
    const nodeEl = node.nodeType === 1 ? node : node.parentElement;
    const card = nodeEl && nodeEl.closest ? nodeEl.closest(".card") : null;
    const sentence = card ? WB.paper.findSentence(Number(card.dataset.i)) : null;
    return {
      text: sel.slice(0, 2000),
      sentence: sentence,
      i: sentence ? sentence.i : -1
    };
  }

  function currentSentence(picked){
    picked = picked || selectionInfo();
    if(picked.sentence) return picked.sentence;
    if(S().activeSentence >= 0) return WB.paper.findSentence(S().activeSentence);
    if(S().followActive && S().followIndex >= 0) return WB.paper.findSentence(S().followIndex);
    return null;
  }

  function buildContext(){
    const sec = WB.paper.currentSection();
    const cur = WB.paper.currentItem();
    const id = WB.paper.currentItemId();
    const picked = selectionInfo();
    const sentence = currentSentence(picked);
    let before = "", after = "";
    if(sentence){
      const idx = cur.sentences.findIndex(function(s){ return s.i === sentence.i; });
      if(idx >= 0){
        before = idx > 0 ? cur.sentences[idx - 1].en : "";
        after = idx + 1 < cur.sentences.length ? cur.sentences[idx + 1].en : "";
      }
    }
    const itemText = cur.sentences.map(function(s){ return s.en; }).join(" ").slice(0, 2000);
    const questionText = cur.question_items.map(function(q){ return q.en; }).join(" ").slice(0, 1500);
    return WB.contextPayload({
      itemId: id,
      title: WB.session.paper.title + " / " + sec.name + " / " + cur.title,
      sentence: sentence ? sentence.i : -1,
      display: sentence ? (sentence.display != null ? sentence.display : sentence.i) : "",
      en: sentence ? sentence.en : "",
      before: before,
      after: after,
      section: sec.name,
      item: cur.title,
      itemText: itemText,
      questionText: questionText,
      selection: picked.text,
      errors: WB.state.errors[id],
      notes: WB.state.notes[id],
      loopStats: WB.state.loopStats[id],
      done: sentence ? !!WB.paper.doneMap()[sentence.i] : null,
      paperDone: WB.paper.totalDone(),
      paperTotal: WB.paper.totalSentences(),
      recentActions: WB.session.recentActions
    });
  }

  async function send(){
    if(S().askStreaming) return;
    if(!WB.api || !WB.api.ready){
      append("error", "AI 助手需要从学习工作台打开（HTTP /cet6/）。" +
        "file:// 打开时仍可以听音频、看原文。");
      return;
    }
    const input = WB.dom.askInput;
    const message = String(input.value || "").trim();
    if(!message) return;
    input.value = "";
    append("user", message);
    const reply = append("assistant", "");
    const meta = el("div", "ask-meta");
    reply.wrap.insertBefore(meta, reply.bubble);

    let answer = "";
    let thinking = "";
    let finalText = "";
    const trace = [];
    const controller = new AbortController();
    S().askAbort = controller;
    setStreaming(true);

    const render = function(){
      let html = "";
      if(thinking){
        html += '<details class="ask-thinking"><summary>思考过程</summary>' +
          mdLite(thinking) + "</details>";
      }
      if(trace.length){
        html += '<div class="ask-tools">' +
          trace.map(function(x){ return "<span>" + U.escapeHtml(x) + "</span>"; }).join("") +
          "</div>";
      }
      html += mdLite(answer || (S().askStreaming ? "正在思考…" : ""));
      reply.bubble.innerHTML = html;
      scrollBottom();
    };
    render();

    const onEvent = function(event){
      const kind = event.kind;
      if(kind === "start"){
        const data = event.data || {};
        if(data.conversation_id){
          setConversationId(data.conversation_id);
          if(WB.dom.askModel) WB.dom.askModel.textContent = data.model || "deepseek-flash";
        }
        meta.textContent = data.model ? "模型：" + data.model : "";
      }else if(kind === "text"){
        answer += String(event.text || "");
        render();
      }else if(kind === "thinking"){
        thinking += String(event.text || "");
        render();
      }else if(kind === "tool_start"){
        const name = (event.data && event.data.name) || "工具";
        trace.push("→ " + name);
        render();
      }else if(kind === "tool_end"){
        const preview = (event.data && event.data.preview) || "完成";
        trace[trace.length - 1] = "✓ " + preview;
        render();
      }else if(kind === "done"){
        finalText = String((event.data && event.data.text) || "");
        if(finalText) answer = finalText;
        render();
      }else if(kind === "error"){
        answer = "出错了：" + (event.text || "未知原因");
        render();
      }
    };

    try{
      await WB.api.stream("/api/agent/chat", {
        message: message,
        conversation_id: currentId() || null,
        module: "cet6",
        surface: "cet6",
        context_snapshot: buildContext()
      }, onEvent, controller.signal);
      if(!answer && !S().askStreaming) answer = "（没有返回内容）";
    }catch(err){
      if(err && err.name === "AbortError"){
        answer = (answer ? answer + "\n\n" : "") + "（已停止）";
      }else{
        answer = "提问失败：" + (WB.api ? WB.api.errorText(err) : String(err));
      }
      render();
    }finally{
      S().askAbort = null;
      S().askSelection = null;
      setStreaming(false);
      render();
      WB.noteAction("提问：" + message.slice(0, 60));
    }
  }

  async function stop(){
    const controller = S().askAbort;
    if(controller) controller.abort();
    if(WB.api && WB.api.ready){
      try{
        await WB.api.post("/api/agent/stop", {conversation_id: currentId() || null});
      }catch(e){}
    }
    setStreaming(false);
  }

  function newConversation(){
    if(S().askStreaming) stop();
    setConversationId(0);
    S().askLoaded = true;
    S().askSelection = null;
    welcome();
    showTab("chat");
    if(WB.dom.askInput) WB.dom.askInput.focus();
  }

  function storedText(content){
    if(content == null) return "";
    if(typeof content === "string") return content;
    return String(content.text || "");
  }

  function renderStored(message){
    const content = message.content || {};
    const role = message.role;
    if(role === "user"){
      const text = storedText(content);
      if(text) append("user", text);
      return;
    }
    if(role === "assistant"){
      const err = typeof content === "object" ? String(content.error || "") : "";
      if(err){
        append("error", "上次回答出错：" + err);
        return;
      }
      const text = storedText(content);
      const thinking = typeof content === "object" ? String(content.thinking || "") : "";
      if(text) append("assistant", text, {thinking: thinking});
    }
  }

  async function loadConversation(id){
    id = Number(id) || 0;
    if(S().askStreaming) await stop();
    if(!id){
      welcome();
      S().askLoaded = true;
      return;
    }
    if(!WB.api || !WB.api.ready){
      welcome();
      return;
    }
    clearMessages();
    append("assistant", "正在读取对话…");
    try{
      const data = await WB.api.get("/api/conversations/" + id);
      clearMessages();
      (data.messages || []).forEach(renderStored);
      if(!(data.messages || []).length) welcome();
      setConversationId(data.id || id);
      S().askLoaded = true;
      if(WB.dom.askModel) WB.dom.askModel.textContent = "deepseek-flash";
      scrollBottom();
    }catch(err){
      clearMessages();
      if(err && err.status === 404){
        setConversationId(0);
        welcome();
      }else{
        append("error", "读取对话失败：" + WB.api.errorText(err));
      }
    }
  }

  function historyLabel(row){
    const stamp = String(row.updated_at || "");
    const short = stamp.length >= 16 ? stamp.slice(5, 16).replace("T", " ") : stamp;
    return short;
  }

  function renderHistory(){
    const box = WB.dom.askHistoryList;
    if(!box) return;
    const q = historyQuery.trim().toLowerCase();
    const rows = historyRows.filter(function(row){
      return !q || String(row.title || "").toLowerCase().indexOf(q) >= 0;
    });
    if(!rows.length){
      box.innerHTML = '<p class="status">' +
        (historyRows.length ? "没有匹配的对话。" : "还没有对话。问一句就会出现在这里。") +
        "</p>";
      return;
    }
    const nowId = currentId();
    box.innerHTML = rows.map(function(row){
      const title = String(row.title || "新对话");
      return '<button type="button" class="ai-history-item' +
        (Number(row.id) === nowId ? " on" : "") + '" data-history="' + Number(row.id) + '">' +
        '<span class="t">' + U.escapeHtml(title) + "</span>" +
        '<span class="m">' + U.escapeHtml(historyLabel(row)) +
          " · " + Number(row.messages || 0) + " 条" +
          (Number(row.id) === nowId ? " · 当前" : "") + "</span>" +
        "</button>";
    }).join("");
  }

  async function loadHistory(){
    if(historyLoading) return;
    const box = WB.dom.askHistoryList;
    if(!box) return;
    if(!WB.api || !WB.api.ready){
      box.innerHTML = '<p class="status">对话历史需要从学习工作台打开（HTTP /cet6/）。</p>';
      return;
    }
    historyLoading = true;
    box.innerHTML = '<p class="status">正在翻历史…</p>';
    try{
      const data = await WB.api.get("/api/conversations?limit=50&module=cet6");
      historyRows = data.items || [];
      renderHistory();
    }catch(err){
      box.innerHTML = '<p class="status">历史读取失败：' + U.escapeHtml(WB.api.errorText(err)) + "</p>";
    }finally{
      historyLoading = false;
    }
  }

  function showTab(name){
    const tab = name || "chat";
    S().askTab = tab;
    document.querySelectorAll("[data-ask-tab]").forEach(function(btn){
      btn.classList.toggle("on", btn.dataset.askTab === tab);
    });
    if(WB.dom.askChatView) WB.dom.askChatView.classList.toggle("hidden", tab !== "chat");
    if(WB.dom.askAnalysisView) WB.dom.askAnalysisView.classList.toggle("hidden", tab !== "analysis");
    if(WB.dom.askHistoryView) WB.dom.askHistoryView.classList.toggle("hidden", tab !== "history");
    if(tab === "history") loadHistory();
    if(tab === "analysis" && WB.insights && WB.insights.showCurrent) WB.insights.showCurrent();
    if(tab === "chat"){
      scrollBottom();
      if(WB.dom.askInput) WB.dom.askInput.focus();
    }
  }

  function openPanel(tab){
    const panel = WB.dom.askPanel;
    if(!panel) return;
    panel.classList.remove("hidden");
    if(WB.dom.askBtn){
      WB.dom.askBtn.classList.add("on");
      WB.dom.askBtn.setAttribute("aria-expanded", "true");
    }
    showTab(tab || S().askTab || "chat");
    if(!S().askLoaded){
      S().askLoaded = true;
      loadConversation(currentId());
    }
  }

  function closePanel(){
    const panel = WB.dom.askPanel;
    if(!panel) return;
    panel.classList.add("hidden");
    if(WB.dom.askBtn){
      WB.dom.askBtn.classList.remove("on");
      WB.dom.askBtn.setAttribute("aria-expanded", "false");
    }
  }

  function togglePanel(){
    const panel = WB.dom.askPanel;
    if(!panel) return;
    if(panel.classList.contains("hidden")) openPanel("chat");
    else closePanel();
  }

  // 句子卡片 / 划词浮钮 / 快捷键都从这里进：保留现场，再打开抽屉。
  function openFor(opts){
    opts = opts || {};
    if(opts.text != null){
      S().askSelection = {
        text: String(opts.text || "").slice(0, 2000),
        i: opts.sentence != null ? Number(opts.sentence) : -1
      };
    }
    openPanel("chat");
    if(opts.prefill != null && WB.dom.askInput){
      WB.dom.askInput.value = String(opts.prefill);
      WB.dom.askInput.focus();
      WB.dom.askInput.setSelectionRange(WB.dom.askInput.value.length,
        WB.dom.askInput.value.length);
    }
  }

  function clampFabTop(top){
    const btn = WB.dom.askBtn;
    const h = btn ? btn.offsetHeight : 58;
    // 底部给固定播放条留位置，别让圆圈拖到播放条上面。
    return U.clamp(Number(top) || 0, 8, Math.max(8, window.innerHeight - h - 96));
  }

  function placeFab(top){
    const btn = WB.dom.askBtn;
    if(!btn) return;
    btn.style.top = clampFabTop(top) + "px";
    btn.style.bottom = "auto";
  }

  // AI 圆圈只上下移动：左右仍然贴右边，避免挡住正文中间。
  function initFabDrag(){
    const btn = WB.dom.askBtn;
    if(!btn) return;
    const saved = WB.store.loadAi();
    if(saved.fabTop != null) placeFab(saved.fabTop);

    btn.addEventListener("pointerdown", function(e){
      if(e.button != null && e.button !== 0) return;
      const rect = btn.getBoundingClientRect();
      fabDrag = {y:e.clientY, top:rect.top, moved:false, id:e.pointerId};
      try{ btn.setPointerCapture(e.pointerId); }catch(err){}
    });
    btn.addEventListener("pointermove", function(e){
      if(!fabDrag || e.pointerId !== fabDrag.id) return;
      const dy = e.clientY - fabDrag.y;
      if(Math.abs(dy) > 4) fabDrag.moved = true;
      if(!fabDrag.moved) return;
      placeFab(fabDrag.top + dy);
    });
    btn.addEventListener("pointerup", function(e){
      if(!fabDrag || e.pointerId !== fabDrag.id) return;
      const moved = fabDrag.moved;
      const top = btn.getBoundingClientRect().top;
      fabDrag = null;
      try{ btn.releasePointerCapture(e.pointerId); }catch(err){}
      if(moved){
        placeFab(top);
        WB.store.saveAi({fabTop:clampFabTop(top)});
        suppressFabClick = true;
        setTimeout(function(){ suppressFabClick = false; }, 0);
      }
    });
    btn.addEventListener("pointercancel", function(){ fabDrag = null; });
    btn.addEventListener("click", function(e){
      if(suppressFabClick){
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      togglePanel();
    });
    window.addEventListener("resize", function(){
      const ai = WB.store.loadAi();
      if(ai.fabTop != null && btn.style.bottom === "auto"){
        placeFab(ai.fabTop);
      }
    });
  }

  function init(){
    if(bound) return;
    bound = true;
    if(WB.dom.askModel) WB.dom.askModel.textContent = "deepseek-flash";

    initFabDrag();
    WB.dom.askClose.addEventListener("click", closePanel);
    WB.dom.askSend.addEventListener("click", send);
    WB.dom.askStop.addEventListener("click", stop);
    WB.dom.askNew.addEventListener("click", newConversation);
    WB.dom.askInput.addEventListener("keydown", function(e){
      if(e.key === "Enter" && !e.shiftKey){
        e.preventDefault();
        send();
      }
    });

    if(WB.dom.askTabs){
      WB.dom.askTabs.addEventListener("click", function(e){
        const btn = e.target.closest("button[data-ask-tab]");
        if(!btn) return;
        showTab(btn.dataset.askTab);
      });
    }
    if(WB.dom.askSuggest){
      WB.dom.askSuggest.addEventListener("click", function(e){
        const btn = e.target.closest("button[data-suggest]");
        if(!btn) return;
        WB.dom.askInput.value = btn.dataset.suggest || "";
        WB.dom.askInput.focus();
      });
    }
    if(WB.dom.askHistorySearch){
      WB.dom.askHistorySearch.addEventListener("input", function(){
        historyQuery = WB.dom.askHistorySearch.value || "";
        renderHistory();
      });
    }
    if(WB.dom.askHistoryList){
      WB.dom.askHistoryList.addEventListener("click", function(e){
        const btn = e.target.closest("button[data-history]");
        if(!btn) return;
        loadConversation(Number(btn.dataset.history)).then(function(){
          showTab("chat");
        });
      });
    }
  }

  WB.ask = {
    init: init,
    send: send,
    stop: stop,
    buildContext: buildContext,
    togglePanel: togglePanel,
    openPanel: openPanel,
    closePanel: closePanel,
    showTab: showTab,
    openFor: openFor,
    newConversation: newConversation
  };
})(window.WB = window.WB || {});
